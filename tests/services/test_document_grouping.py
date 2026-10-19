"""Keep valid continuations together without merging real or uncertain packets."""

import pytest

from src.backoffice.processing.evidence_contracts import PageObservation
from src.backoffice.processing.workflow import requires_document_grouping


def page(number, *, hint, boundary, printed=None, count=None):
    return PageObservation(
        source_file="statement.pdf",
        page=number,
        source_sha256="a" * 64,
        page_sha256=str(number) * 64,
        document_type="bank_statement",
        confidence=0.98,
        reason="Statement page",
        model="classifier",
        cache_hit=False,
        group_hint=hint,
        boundary=boundary,
        printed_page_number=printed,
        printed_page_count=count,
    )


def test_bank_statement_continuation_can_have_different_source_labels():
    pages = [
        page(1, hint="Example Bank", boundary="starts_document", printed=1, count=2),
        page(2, hint="Account identifier", boundary="continues_document", printed=2, count=2),
    ]
    assert not requires_document_grouping(pages)
    # Provider response order is not physical page order.
    assert not requires_document_grouping(pages[::-1])


@pytest.mark.parametrize(
    "defect", ["second_start", "unknown_boundary", "reset_number", "different_total", "gap"]
)
def test_conflicting_or_unresolved_documents_still_require_grouping(defect):
    first = page(1, hint="Example Bank", boundary="starts_document", printed=1, count=3)
    second = page(2, hint="Account identifier", boundary="continues_document", printed=2, count=3)
    if defect == "second_start":
        second.boundary = "starts_document"
        second.group_hint = first.group_hint  # Even identical labels cannot erase a boundary.
    elif defect == "unknown_boundary":
        second.boundary = "unknown"
    elif defect == "reset_number":
        second.printed_page_number = 1
    elif defect == "different_total":
        second.printed_page_count = 2
    else:
        second.printed_page_number = 3
    assert requires_document_grouping([first, second])


def test_explicit_continuation_does_not_require_a_printed_footer():
    assert not requires_document_grouping(
        [
            page(1, hint="Issuer", boundary="starts_document"),
            page(2, hint="Account", boundary="continues_document"),
        ]
    )
