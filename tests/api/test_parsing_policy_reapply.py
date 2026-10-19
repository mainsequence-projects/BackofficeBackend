"""Explicit policy rechecks retain observations and cannot override reviews."""

from uuid import UUID

import pytest

from src.backoffice.processing.evidence_contracts import ExtractionResponseV2
from src.backoffice.services.application import DR, RV
from src.backoffice.services.parsing import RESULT
from src.backoffice.tables.evidence import FieldEvidenceRecord
from tests.api.test_document_processing import Parser, upload, worker
from tests.api.test_document_processing import flow as flow
from tests.api.test_parsing_admin import complete, draft, policy
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person, post, source


def reapply(client, uid, body=None):
    return client.post(
        f"/admin/documents/{uid}/reapply-parsing-policy",
        json=body or command(expected_revision=1),
    )


def pending(client, current, payload, score="98"):
    policy(client, current, "100")
    person = make_person(client)
    uid = draft(client, person, payload, source(client, person))
    assert complete(client, uid, score).json()["decision"] == "needs_review"
    policy(client, current, "80", revision=1)
    return person, uid


@pytest.mark.parametrize("score,accepted", [("98", True), ("80", True), ("79.99", False)])
def test_saved_score_rechecked_without_changing_facts_history_or_case_policy(
    business, document_fixture, score, accepted
):
    client, current, store = business
    person, uid = pending(client, current, document_fixture("national_identity_card"), score)
    case = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=5,
    )
    original = store.one(DR, document_uid=uid, revision=1)
    original_result = store.one(RESULT, document_uid=uid, revision=1)
    body = command(expected_revision=1)
    response = reapply(client, uid, body)
    assert response.status_code == 200, response.text
    assert reapply(client, uid, body).json() == response.json()
    latest = client.get(f"/documents/{uid}").json()
    assert latest["accepted"] is accepted
    assert latest["revision"] == 2
    assert latest["schema_version"] == original["schema_version"]
    assert latest["payload"] == original["payload"]
    assert latest["raw_document_refs"] == original["raw_document_refs"]
    assert latest["parsing_result"]["parsing_score_percent"] == f"{float(score):.2f}"
    assert latest["parsing_result"]["acceptance_threshold_percent"] == "80.00"
    assert latest["parsing_result"]["policy_revision"] == 2
    assert latest["parsing_result"]["extractor"] == original_result["extractor"]
    assert store.one(DR, document_uid=uid, revision=1) == original
    assert store.one(RESULT, document_uid=uid, revision=1) == original_result
    case_after = client.get(f"/cases/{case['uid']}").json()
    assert case_after["document_set_version"] == 5
    assert case_after["revision"] == case["revision"]
    # A repeated sweep with a fresh operation does not add another revision.
    skipped = reapply(client, uid, command(expected_revision=2)).json()
    assert skipped["outcome"] == ("skipped_reviewed" if accepted else "skipped_current_policy")
    assert store.count(DR) == 2


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_human_decisions_are_preserved(business, document_fixture, decision):
    client, current, store = business
    _, uid = pending(client, current, document_fixture("national_identity_card"))
    post(
        client,
        f"/documents/{uid}/reviews",
        expected_revision=1,
        expected_decision_sequence=0,
        decision=decision,
        reason="Source inspected by a person",
    )
    original = client.get(f"/documents/{uid}").json()
    response = reapply(client, uid)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "skipped_reviewed"
    assert client.get(f"/documents/{uid}").json() == original
    assert store.count(DR) == store.count(RV) == store.count(RESULT) == 1


def test_missing_scores_and_incomplete_attributes_are_not_accepted(business, document_fixture):
    client, current, store = business
    _, missing = pending(client, current, document_fixture("national_identity_card"), None)
    assert reapply(client, missing).json()["outcome"] == "skipped_score_missing"
    assert client.get(f"/documents/{missing}").json()["revision"] == 1
    # Use a new subject so the same helper can create a separate unparsed draft.
    person = make_person(client)
    uid = draft(client, person, {}, source(client, person))
    assert reapply(client, uid).json()["outcome"] == "skipped_score_missing"
    complete(client, uid, "98")
    policy(client, current, "80", revision=2)
    result = reapply(client, uid).json()
    assert result["parsing_result"]["reason_code"] == "invalid_document_attributes"
    assert client.get(f"/documents/{uid}").json()["accepted"] is False


def test_recheck_requires_admin_current_revision_and_server_owned_score(business, document_fixture):
    client, current, _ = business
    _, uid = pending(client, current, document_fixture("national_identity_card"))
    current[0].organization_admin = False
    assert reapply(client, uid).status_code == 403
    current[0].organization_admin = True
    assert reapply(client, uid, command(expected_revision=2)).status_code == 409
    assert (
        reapply(client, uid, command(expected_revision=1, parsing_score_percent="100")).status_code
        == 422
    )


@pytest.mark.parametrize("fail_after", [1, 3, 5, 7, 10])
def test_recheck_resumes_both_durable_steps_after_lost_response(
    business, document_fixture, fail_after
):
    client, current, store = business
    _, uid = pending(client, current, document_fixture("national_identity_card"))
    body = command(expected_revision=1)
    store.fail_after_write = fail_after
    with pytest.raises(TimeoutError):
        reapply(client, uid, body)
    response = reapply(client, uid, body)
    assert response.status_code == 200, response.text
    assert reapply(client, uid, body).json() == response.json()
    assert store.count(DR) == store.count(RESULT) == 2
    assert store.count(RV) == 1
    assert client.get(f"/documents/{uid}").json()["accepted"] is True


@pytest.mark.parametrize("incomplete", [False, True])
def test_extraction_observations_survive_recheck_and_still_block_acceptance(flow, incomplete):
    client, current, store, bucket, _, person, original = flow
    policy(client, current, "100", document_type="passport")

    class Observations(Parser):
        def extract(self, request):
            data = super().extract(request).model_dump()
            data["evidence_complete"] = not incomplete
            return ExtractionResponseV2.model_validate(data)

    result = worker(current, bucket, Observations(original.payload, confidence=0.98), store).run(
        upload(client, person).json()["uid"]
    )
    uid = result["document"]["uid"]
    assert result["completion"]["decision"] == "needs_review"
    policy(client, current, "80", revision=1, document_type="passport")
    before = store.one(DR, document_uid=uid, revision=1)
    response = reapply(client, uid)
    assert response.status_code == 200, response.text
    after = store.one(DR, document_uid=uid, revision=2)
    assert after["extraction_evidence"] == before["extraction_evidence"]
    fields = FieldEvidenceRecord.__table__
    old_fields = store.rows(fields, fields.c.revision_uid == UUID(before["uid"]))
    new_fields = store.rows(fields, fields.c.revision_uid == UUID(after["uid"]))
    assert old_fields and len(old_fields) == len(new_fields)

    def observations(rows):
        return sorted((r["field_path"], str(r["provenance"])) for r in rows)

    assert observations(old_fields) == observations(new_fields)
    assert client.get(f"/documents/{uid}").json()["accepted"] is not incomplete
    if incomplete:
        assert response.json()["parsing_result"]["reason_code"] == "extraction_evidence_incomplete"
