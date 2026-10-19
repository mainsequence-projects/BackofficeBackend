"""Minimal source facts survive the real draft, submission and parser workflows."""

import pytest

from src.backoffice.schemas.registry import LATEST_DOCUMENT_VERSIONS
from tests.api.test_document_processing import Parser, upload, worker
from tests.api.test_document_processing import flow as flow
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person, post, source
from tests.happy_cases import load_happy_cases
from tests.models.test_document_minimums import MINIMUM_FIELDS, minimum_payload


@pytest.mark.parametrize("source_name,payload", load_happy_cases())
def test_authoritative_happy_case_submits_without_model_invented_fields(
    business, source_name, payload
):
    client, _, _ = business
    person = make_person(client)
    kind = payload["document_type"]
    draft = post(
        client,
        f"/persons/{person}/documents",
        document_type=kind,
        schema_version=LATEST_DOCUMENT_VERSIONS[kind],
        payload=payload,
        raw_document_refs=[{"raw_document_uid": source(client, person)}],
    )
    post(client, f"/documents/{draft['uid']}/submit", expected_revision=1)
    document = client.get(f"/documents/{draft['uid']}").json()
    assert document["status"] == "submitted", source_name
    assert document["accepted"] is False


@pytest.mark.parametrize("kind", MINIMUM_FIELDS)
def test_minimum_document_submission_and_schema(business, document_fixture, kind):
    client, _, _ = business
    person = make_person(client)
    version = LATEST_DOCUMENT_VERSIONS[kind]
    schema = client.get(f"/document-types/{kind}/schema?version={version}").json()
    assert set(schema["canonical_schema"]["required"]) == set(MINIMUM_FIELDS[kind].split())
    payload = minimum_payload(kind, document_fixture)
    draft = post(
        client,
        f"/persons/{person}/documents",
        document_type=kind,
        schema_version=version,
        payload=payload,
        raw_document_refs=[{"raw_document_uid": source(client, person)}],
    )
    post(client, f"/documents/{draft['uid']}/submit", expected_revision=1)
    document = client.get(f"/documents/{draft['uid']}").json()
    assert document["status"] == "submitted"
    assert document["schema_version"] == version
    assert document["accepted"] is False


@pytest.mark.parametrize("kind", ["national_identity_card", "utility_bill", "payslip"])
def test_parser_completes_without_ancillary_fields(flow, document_fixture, kind):
    client, current, store, bucket, _, _, _ = flow
    person = make_person(client)
    parser = Parser(minimum_payload(kind, document_fixture), kind=kind)
    response = upload(client, person)
    assert response.status_code == 202
    result = worker(current, bucket, parser, store).run(response.json()["uid"])
    assert result["status"] == "completed", result
    assert result["completion"]["reason_code"] == "parsing_policy_missing"
    document = client.get(f"/documents/{result['document']['uid']}").json()
    assert document["status"] == "submitted"
    assert document["schema_version"] == LATEST_DOCUMENT_VERSIONS[kind]


def test_version_one_submission_remains_strict(business, document_fixture):
    client, _, _ = business
    person = make_person(client)
    draft = post(
        client,
        f"/persons/{person}/documents",
        document_type="payslip",
        schema_version=1,
        payload=minimum_payload("payslip", document_fixture),
        raw_document_refs=[{"raw_document_uid": source(client, person)}],
    )
    assert (
        client.post(
            f"/documents/{draft['uid']}/submit", json=command(expected_revision=1)
        ).status_code
        == 422
    )
