"""Convert genuine classifier confidence to the completion contract's percentage scale.

This adapter never derives confidence from attribute completeness or explicit type
selection. It does not choose a policy or accept a document.
"""

from decimal import ROUND_FLOOR, Decimal
from typing import Any

from pydantic import Field, StrictFloat, StrictInt, StrictStr

from ..models.common import ContractModel
from ..schemas.registry import get_document_model


class ClassifiedPage(ContractModel):
    source_file: StrictStr = Field(min_length=1)
    page: StrictInt = Field(ge=1)
    document_type: StrictStr | None
    confidence: StrictFloat | None = Field(default=None, ge=0, le=1)


class DocumentClassification(ContractModel):
    document_type: str | None
    classification_confidence_percent: Decimal | None = Field(default=None, ge=0, le=100)
    aggregation: str = "minimum_page_confidence_v1"
    reason_code: str


def confidence_percent(confidence: float | int | None) -> Decimal | None:
    """Convert [0,1] to [0,100], rounding down to the stored 0.01% precision."""
    if confidence is None:
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("Classification confidence must be a numeric probability")
    value = Decimal(str(confidence))
    if not value.is_finite() or not 0 <= value <= 1:
        raise ValueError("Classification confidence must be finite and between zero and one")
    return (value * 100).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def document_classification(
    pages: list[dict[str, Any]], *, expected_pages: set[tuple[str, int]]
) -> DocumentClassification:
    """Aggregate exactly the source/page manifest of one logical document.

    ParsingMotor returns provenance in additional fields; select the classification
    fields explicitly. The caller retains the original response in its processing run.
    The expected manifest comes from the ingested source, not the classifier itself.
    """
    if not pages or not expected_pages:
        raise ValueError("A nonempty source page manifest is required")
    parsed = [
        ClassifiedPage.model_validate(
            {key: page[key] for key in ClassifiedPage.model_fields if key in page}
        )
        for page in pages
    ]
    actual = [(page.source_file, page.page) for page in parsed]
    if len(actual) != len(set(actual)) or set(actual) != expected_pages:
        raise ValueError("Classification pages do not match the source manifest")
    types = {page.document_type for page in parsed}
    if None in types or len(types) != 1:
        return DocumentClassification(document_type=None, reason_code="mixed_or_unknown_type")
    document_type = next(iter(types))
    try:
        get_document_model(document_type)
    except ValueError:
        return DocumentClassification(document_type=None, reason_code="unsupported_type")
    if any(page.confidence is None for page in parsed):
        return DocumentClassification(document_type=document_type, reason_code="confidence_missing")
    return DocumentClassification(
        document_type=document_type,
        classification_confidence_percent=confidence_percent(
            min(page.confidence for page in parsed)
        ),
        reason_code="classified",
    )
