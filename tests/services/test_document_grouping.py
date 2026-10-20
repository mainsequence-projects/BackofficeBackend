"""Keep valid continuations together without merging real or uncertain packets."""

import pytest

from src.backoffice.processing.evidence_contracts import PageObservation
from src.backoffice.processing.packets import document_groups
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


def test_packet_plan_uses_physical_pages_and_keeps_continuations_together():
    first = page(1, hint="ID", boundary="starts_document", printed=1, count=1)
    first.document_type = "national_identity_card"
    pages = [
        first,
        page(2, hint="Bank", boundary="starts_document", printed=1, count=2),
        page(3, hint="Account", boundary="continues_document", printed=2, count=2),
    ]
    assert document_groups(pages[::-1]) == [
        {"document_type": "national_identity_card", "pages": [1]},
        {"document_type": "bank_statement", "pages": [2, 3]},
    ]


@pytest.mark.parametrize(
    "defect", ["unknown_boundary", "unknown_type", "missing_page", "mixed_continuation", "gap"]
)
def test_ambiguous_packet_plan_never_creates_partial_groups(defect):
    pages = [
        page(1, hint="A", boundary="starts_document", printed=1, count=1),
        page(2, hint="B", boundary="starts_document", printed=1, count=2),
        page(3, hint="B", boundary="continues_document", printed=2, count=2),
    ]
    if defect == "unknown_boundary":
        pages[1].boundary = "unknown"
    elif defect == "unknown_type":
        pages[1].document_type = None
    elif defect == "missing_page":
        pages.pop()
    elif defect == "mixed_continuation":
        pages[2].document_type = "passport"
    else:
        pages[2].page = 4
    assert document_groups(pages) is None


def test_isolated_type_between_closed_and_started_documents_has_its_own_group():
    pages = [
        page(1, hint="Payslip", boundary="starts_document", printed=1, count=1),
        page(2, hint=None, boundary="unknown"),
        page(3, hint="Employer", boundary="starts_document", printed=1, count=1),
    ]
    pages[0].document_type = "payslip"
    pages[1].document_type = "utility_bill"
    pages[2].document_type = "employer_confirmation"
    groups = document_groups(pages)
    assert groups[1] == {
        "document_type": "utility_bill",
        "pages": [2],
        "boundary_basis": "isolated_type_between_complete_boundaries",
    }
    # A different type alone is insufficient when previous pagination is incomplete.
    pages[0].printed_page_count = 2
    assert document_groups(pages) is None
    pages[0].printed_page_count = 1
    pages[2].boundary = "unknown"
    assert document_groups(pages) is None
