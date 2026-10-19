from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.backoffice.services.parsing_confidence import confidence_percent, document_classification


@pytest.mark.parametrize(
    "value,expected",
    [(0, "0.00"), (1, "100.00"), (0.6, "60.00"), (0.599999, "59.99"), (0.60001, "60.00")],
)
def test_probability_conversion_never_promotes_a_below_threshold_score(value, expected):
    assert confidence_percent(value) == Decimal(expected)


@pytest.mark.parametrize("value", [True, False, "0.60", 60, -0.01, float("nan"), float("inf")])
def test_invalid_probability_rejected(value):
    with pytest.raises(ValueError):
        confidence_percent(value)


def test_missing_confidence_is_not_invented():
    assert confidence_percent(None) is None


def pages():
    return [
        {
            "source_file": "passport.pdf",
            "page": 1,
            "document_type": "passport",
            "confidence": 0.99,
            "model": "classifier",
        },
        {"source_file": "passport.pdf", "page": 2, "document_type": "passport", "confidence": 0.60},
    ]


MANIFEST = {("passport.pdf", 1), ("passport.pdf", 2)}


def test_one_document_uses_lowest_page_score():
    result = document_classification(pages(), expected_pages=MANIFEST)
    assert result.document_type == "passport"
    assert result.classification_confidence_percent == Decimal("60.00")
    assert result.aggregation == "minimum_page_confidence_v1"


@pytest.mark.parametrize("document_type", [None, "bank_statement"])
def test_mixed_or_unknown_pages_require_resolution(document_type):
    result = pages()
    result[1]["document_type"] = document_type
    decision = document_classification(result, expected_pages=MANIFEST)
    assert decision.document_type is None
    assert decision.classification_confidence_percent is None


def test_missing_page_confidence_is_not_replaced_by_other_page():
    result = pages()
    del result[1]["confidence"]
    decision = document_classification(result, expected_pages=MANIFEST)
    assert decision.document_type == "passport"
    assert decision.classification_confidence_percent is None


@pytest.mark.parametrize("mode", ["missing", "duplicate", "extra", "wrong_source"])
def test_manifest_mismatch_is_rejected(mode):
    result = pages()
    if mode == "missing":
        result.pop()
    if mode == "duplicate":
        result.append(result[0])
    if mode == "extra":
        result.append({**result[0], "page": 3})
    if mode == "wrong_source":
        result[0]["source_file"] = "different.pdf"
    with pytest.raises(ValueError, match="manifest"):
        document_classification(result, expected_pages=MANIFEST)


def test_provider_string_score_is_not_coerced():
    result = pages()
    result[0]["confidence"] = "0.9"
    with pytest.raises(ValidationError):
        document_classification(result, expected_pages=MANIFEST)
