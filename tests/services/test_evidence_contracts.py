"""The opt-in parser wire format can describe evidence, not decide a case."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.backoffice.processing.contracts import (
    ClassificationResponse,
    ClassifyRequest,
    ExtractionResponse,
)
from src.backoffice.processing.evidence_contracts import (
    ClassificationResponseV2,
    ClassifyRequestV2,
    ExtractionResponseV2,
    ExtractRequestV2,
)


def page():
    return {
        "source_file": "packet.pdf",
        "page": 5,
        "source_sha256": "a" * 64,
        "page_sha256": "b" * 64,
    }


def classification():
    return {
        "contract_version": 2,
        "pages": [
            {
                **page(),
                "document_type": "payslip",
                "confidence": 0.95,
                "reason": "Payroll heading",
                "model": "reader/1",
                "cache_hit": False,
                "printed_page_number": 1,
                "printed_page_count": 1,
                "group_hint": "payroll-september",
                "boundary": "starts_document",
            }
        ],
    }


def extraction():
    return {
        "contract_version": 2,
        "document_type": "payslip",
        "schema_version": 1,
        "schema_hash": "c" * 64,
        "status": "draft",
        "attributes": {"document_type": "payslip", "net_pay": {"amount": "56000.00"}},
        "canonical_schema_valid": False,
        "canonical_schema_errors": [{"path": [], "keyword": "required"}],
        "pages": [page()],
        "model": "reader/1",
        "cache_hit": False,
        "normalization_version": "decimal-string/1",
        "evidence_complete": True,
        "field_evidence": [
            {
                "pointer": "/net_pay/amount",
                "agreement": "single_reader",
                "selected_reader_id": "ocr",
                "candidates": [
                    {
                        "reader_id": "ocr",
                        "model": "ocr/1",
                        "value": "56000.00",
                        "confidence": 0.93,
                        "locations": [
                            {
                                "source_file": "packet.pdf",
                                "page": 5,
                                "bounding_box": [0.1, 0.2, 0.4, 0.3],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_v2_is_explicit_and_does_not_change_v1_envelopes():
    request = {
        "files": [{"filename": "source.pdf", "content_base64": "YQ=="}],
        "document_types": [{"document_type": "payslip", "description": "Payroll evidence"}],
    }
    assert "contract_version" not in ClassifyRequest.model_validate(request).model_dump()
    with pytest.raises(ValidationError):
        ClassifyRequestV2.model_validate(request)
    ClassifyRequestV2.model_validate({**request, "contract_version": 2})
    ClassificationResponseV2.model_validate(classification())
    ExtractionResponseV2.model_validate(extraction())
    for model, payload in (
        (ClassificationResponse, classification()),
        (ExtractionResponse, extraction()),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.parametrize(
    "key",
    [
        "accepted",
        "recommended_next_step",
        "checks",
        "missing_documents",
        "reviewer",
        "rules_version",
    ],
)
def test_business_outputs_are_rejected(key):
    with pytest.raises(ValidationError):
        ExtractionResponseV2.model_validate({**extraction(), key: "passed"})
    with pytest.raises(ValidationError):
        ClassificationResponseV2.model_validate({**classification(), key: "passed"})


@pytest.mark.parametrize(
    "defect",
    [
        "foreign_page",
        "unknown_reader",
        "wrong_value",
        "wrong_pointer",
        "bad_box",
        "duplicate_pointer",
        "uncovered",
        "duplicate_page",
        "false_agreement",
        "no_citation",
    ],
)
def test_evidence_cannot_claim_unbound_or_inconsistent_provenance(defect):
    payload = extraction()
    field = payload["field_evidence"][0]
    candidate = field["candidates"][0]
    if defect == "foreign_page":
        candidate["locations"][0]["page"] = 6
    elif defect == "unknown_reader":
        field["selected_reader_id"] = "invented"
    elif defect == "wrong_value":
        candidate["value"] = "41000.00"
    elif defect == "wrong_pointer":
        field["pointer"] = "/nonexistent"
    elif defect == "bad_box":
        candidate["locations"][0]["bounding_box"] = [0.5, 0.2, 0.1, 0.3]
    elif defect == "duplicate_pointer":
        payload["field_evidence"].append(deepcopy(field))
    elif defect == "uncovered":
        payload["attributes"]["net_pay"]["currency"] = "CZK"
    elif defect == "duplicate_page":
        payload["pages"].append(page())
    elif defect == "false_agreement":
        field["agreement"] = "agree"
    elif defect == "no_citation":
        candidate["locations"] = []
    with pytest.raises(ValidationError):
        ExtractionResponseV2.model_validate(payload)


def test_dual_reading_disagreement_is_evidence_even_without_a_selected_value():
    payload = extraction()
    field = payload["field_evidence"][0]
    second = deepcopy(field["candidates"][0])
    second.update(reader_id="vision", model="vision/2", value="41000.00", confidence=None)
    second["locations"][0]["bounding_box"] = None
    field["candidates"].append(second)
    field.update(agreement="disagree", selected_reader_id=None)
    payload["attributes"]["net_pay"]["amount"] = None
    result = ExtractionResponseV2.model_validate(payload)
    assert result.field_evidence[0].candidates[1].confidence is None
    assert result.status == "draft"


def test_array_evidence_and_escaped_json_pointers():
    payload = extraction()
    payload["attributes"] = {"document_type": "payslip", "items": [{"a/b~c": "56000.00"}]}
    field = payload["field_evidence"][0]
    field["pointer"] = "/items/0/a~1b~0c"
    ExtractionResponseV2.model_validate(payload)
    for invalid in ("/items/01/a~1b~0c", "/items/2/a~1b~0c", "/items/0/a~2b"):
        field["pointer"] = invalid
        with pytest.raises(ValidationError):
            ExtractionResponseV2.model_validate(payload)


def test_page_observations_and_selection_remain_physical_not_business_grouping():
    payload = classification()
    payload["pages"][0]["printed_page_number"] = 2
    with pytest.raises(ValidationError):
        ClassificationResponseV2.model_validate(payload)
    request = {
        "contract_version": 2,
        "files": [{"filename": "packet.pdf", "content_base64": "YQ=="}],
        "document_type": "payslip",
        "schema_version": 1,
        "schema_hash": "c" * 64,
        "canonical_schema": {},
        "output_schema": {},
        "page_selection": [5, 3],
    }
    assert ExtractRequestV2.model_validate(request).page_selection == [5, 3]
    request["page_selection"] = [5, 5]
    with pytest.raises(ValidationError):
        ExtractRequestV2.model_validate(request)
