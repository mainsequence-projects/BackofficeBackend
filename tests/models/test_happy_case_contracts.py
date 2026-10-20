"""Required fields must be supported by authoritative happy-case inputs."""

import hashlib
import json
from datetime import date

import pytest
from pydantic import ValidationError

from src.backoffice.models.document_set import DocumentOption
from src.backoffice.schemas.catalog import document_schema
from src.backoffice.schemas.drafts import complete_draft
from src.backoffice.schemas.registry import LATEST_DOCUMENT_VERSIONS
from src.backoffice.services.reconciliation import assess
from tests.happy_cases import ROOT, load_happy_cases

CASES = load_happy_cases()


def test_copied_happy_cases_match_recorded_source_hashes():
    for source in json.loads((ROOT / "happy_cases/sources.json").read_text()):
        data = (ROOT / "happy_cases" / source["fixture"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source["sha256"]


def test_remaining_seven_types_have_authoritative_examples():
    assert {payload["document_type"] for _, payload in CASES} == {
        "national_identity_card",
        "bank_statement",
        "tax_clearance_certificate",
        "passport",
        "employment_contract",
        "tax_return",
        "source_of_funds_evidence",
    }


@pytest.mark.parametrize("source,payload", CASES, ids=[source for source, _ in CASES])
def test_happy_case_has_every_obligatory_field_without_enrichment(source, payload):
    kind = payload["document_type"]
    version = LATEST_DOCUMENT_VERSIONS[kind]
    schema = document_schema(kind, version).canonical_schema
    assert set(schema["required"]) <= payload.keys(), source
    parsed = complete_draft(kind, payload, version)
    for name in (
        "issue_date",
        "issuing_country",
        "validity_type",
        "bank_name",
        "currency",
        "statement_as_printed",
    ):
        if name not in payload and name in type(parsed).model_fields:
            assert getattr(parsed, name) is None, (source, name)
    assert type(parsed).model_validate_json(parsed.model_dump_json()) == parsed


def test_optional_identity_metadata_does_not_waive_validity():
    source = next(p for _, p in CASES if p["document_type"] == "national_identity_card")
    payload = complete_draft("national_identity_card", source, 2).model_dump(mode="json")
    option = DocumentOption(
        document_type="national_identity_card", schema_version=2, require_unexpired=True
    )
    person = {"full_name": payload["full_name"], "date_of_birth": payload["date_of_birth"]}

    def result():
        return assess(
            {
                "status": "submitted",
                "review_status": "accepted",
                "accepted": True,
                "payload": payload,
            },
            option,
            person,
            date(2026, 10, 19),
        )

    assert result() == ("satisfied", "QUALIFYING_DOCUMENT", [])
    payload["expiration_date"] = "2020-01-01"
    assert result()[1] == "DOCUMENT_EXPIRED"
    payload["expiration_date"] = None
    assert result()[1] == "VALIDITY_UNKNOWN"


def test_optional_account_currency_does_not_waive_money_validation():
    source = next(p for _, p in CASES if p["document_type"] == "bank_statement")
    payload = {**source, "closing_balance": {"amount": "123.00", "currency": "CZK"}}
    assert complete_draft("bank_statement", payload, 2).currency is None
    with pytest.raises(ValidationError, match="balance currency"):
        complete_draft("bank_statement", {**payload, "currency": "EUR"}, 2)
    with pytest.raises(ValidationError):
        complete_draft("bank_statement", {**source, "closing_balance": {"amount": "123.00"}}, 2)


def test_unprinted_tax_transcription_does_not_invent_clearance():
    source = next(p for _, p in CASES if p["document_type"] == "tax_clearance_certificate")
    for statement in ("no_arrears", "arrears_reported", "not_stated"):
        parsed = complete_draft(
            "tax_clearance_certificate", {**source, "arrears_statement": statement}, 2
        )
        assert parsed.statement_as_printed is None
        assert parsed.arrears_statement == statement
        assert parsed.arrears_amount is None
