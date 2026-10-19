"""Shared Job -> cited parser observations -> frozen Back Office decisions, for both products."""

from uuid import uuid4

import pytest

from src.backoffice.processing.comparison_contracts import (
    CompareDocumentsResponse,
    ComparisonObservation,
    cited_fact,
)
from src.backoffice.services.application import EV, RUN, Application, canonical
from tests.api.test_document_processing import Parser, upload, worker
from tests.api.test_document_processing import flow as flow
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, post


class ComparisonParser:
    def __init__(self):
        self.calls = []
        self.uncertain = False
        self.bad_hash = False
        self.callback = None

    def compare(self, request):
        self.calls.append(request)
        if self.callback:
            self.callback()
        return CompareDocumentsResponse(
            contract_version=1,
            request_sha256="f" * 64 if self.bad_hash else request.checksum(),
            model="fixture-comparison-model",
            cache_hit=False,
            observations=[
                ComparisonObservation(
                    key=q.key,
                    comparability="uncertain" if self.uncertain else "comparable",
                    relationship="equivalent",
                    explanation="Observed supplied evidence; no policy decision.",
                    left=cited_fact(request, q.left),
                    right=cited_fact(request, q.right),
                    context=[cited_fact(request, ref) for ref in q.context],
                )
                for q in request.comparisons
            ],
        )


def prepare(flow, document_fixture, product="loan", review=True):
    client, current, store, bucket, dispatcher, person, _ = flow
    current[0].reviewer = True
    kinds = (
        ["loan_contract", "employer_confirmation"]
        if product == "loan"
        else ["passport", "national_identity_card"]
    )
    docs = []
    for kind in kinds:
        parser = Parser(document_fixture(kind), kind=kind)
        result = worker(current, bucket, parser, store).run(upload(client, person).json()["uid"])
        assert result["status"] == "completed", result
        uid = result["document"]["uid"]
        if review:
            post(
                client,
                f"/documents/{uid}/reviews",
                expected_revision=1,
                expected_decision_sequence=0,
                decision="accepted",
                reason="Verified source",
            )
        docs.append(uid)
    assignment = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="loan_requirements" if product == "loan" else "new_account_requirements",
        document_set_version=4 if product == "loan" else 5,
    )
    post_body = command(expected_revision=1, document_uids=docs)
    assert (
        client.put(f"/assignments/{assignment['uid']}/documents", json=post_body).status_code == 200
    )
    return assignment["uid"], docs


def launch(client, assignment, body=None):
    response = client.post(
        f"/assignments/{assignment}/evaluations", json=body or command(expected_revision=2)
    )
    assert response.status_code == 202, response.text
    return response.json()["processing_run_uid"]


@pytest.mark.parametrize("product,expected", [("loan", "failed"), ("account", "satisfied")])
def test_products_use_one_worker_with_cited_frozen_findings(
    flow, document_fixture, product, expected
):
    client, current, store, bucket, dispatcher, _, _ = flow
    assignment, docs = prepare(flow, document_fixture, product)
    before = client.get(f"/assignments/{assignment}/status").json()
    assert before["findings"][-1]["reason_code"] == "COMPARISON_OBSERVATIONS_REQUIRED"
    body = command(expected_revision=2)
    uid = launch(client, assignment, body)
    assert dispatcher.calls[-1] == uid
    parser = ComparisonParser()
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    evaluation = client.get(f"/evaluations/{result['evaluation']['uid']}").json()
    assert not evaluation["stale"]
    finding = next(
        f for f in evaluation["findings"] if f["requirement_key"].endswith("consistency")
    )
    assert finding["status"] == expected
    assert any(r.get("citations") for r in finding["document_references"])
    request = parser.calls[0].model_dump()
    assert all("tolerance" not in str(k) for k in request)
    assert "absolute_tolerance" not in canonical(request)
    assert {d["document_id"] for d in request["documents"]} == set(docs)
    assert "comparison_result" in evaluation["input_snapshot"]
    assert (
        client.get(f"/assignments/{assignment}/status").json()["findings"][-1]["status"] == expected
    )
    # Read-only assessment and duplicate delivery never call the model again.
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    again = client.post(f"/assignments/{assignment}/evaluations", json=body)
    assert again.status_code == 201 and again.json()["uid"] == evaluation["uid"]
    assert len(parser.calls) == 1
    assert client.get(f"/processing-runs/{uid}").json()["evaluation"]["uid"] == evaluation["uid"]


def test_misbound_response_is_retryable_and_never_becomes_a_finding(flow, document_fixture):
    client, current, store, bucket, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture)
    uid = launch(client, assignment)
    parser = ComparisonParser()
    parser.bad_hash = True
    assert worker(current, bucket, parser, store).run(uid)["status"] == "failed"
    assert store.count(EV) == 0
    assert "comparison_response" not in store.one(RUN, uid=uid)["result"]
    parser.bad_hash = False
    assert client.post(f"/processing-runs/{uid}/retry", json=command()).status_code == 202
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    assert len(parser.calls) == 2


def test_document_edit_during_comparison_requires_a_fresh_evaluation(flow, document_fixture):
    client, current, store, bucket, _, _, _ = flow
    assignment, docs = prepare(flow, document_fixture)
    uid = launch(client, assignment)
    parser = ComparisonParser()

    def edit():
        doc = client.get(f"/documents/{docs[0]}").json()
        response = client.patch(
            f"/documents/{docs[0]}/draft",
            json=command(
                expected_revision=1,
                payload=doc["payload"],
                raw_document_refs=doc["raw_document_refs"],
            ),
        )
        assert response.status_code == 200  # Provider calls hold no case lock.

    parser.callback = edit
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "needs_input", result
    assert result["error_code"] == "comparison_inputs_changed_start_new_evaluation"
    assert store.count(EV) == 0
    assert client.post(f"/processing-runs/{uid}/retry", json=command()).status_code == 409


def test_uncertain_semantics_never_become_automatic_completion(flow, document_fixture):
    client, current, store, bucket, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture, "account")
    uid = launch(client, assignment)
    parser = ComparisonParser()
    parser.uncertain = True
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    finding = client.get(f"/assignments/{assignment}/status").json()["findings"][-1]
    assert finding["status"] == "pending_review"


def test_unreviewed_documents_are_not_sent_to_parser(flow, document_fixture):
    client, current, store, bucket, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture, review=False)
    parser = ComparisonParser()
    result = worker(current, bucket, parser, store).run(launch(client, assignment))
    assert result["status"] == "completed", result
    assert parser.calls == []
    assert (
        client.get(f"/assignments/{assignment}/status").json()["findings"][-1]["reason_code"]
        == "COMPARISON_DOCUMENT_REVIEW_REQUIRED"
    )


def test_unauthorized_person_cannot_start_read_or_retry_comparison(flow, document_fixture):
    client, current, store, _, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture)
    uid = launch(client, assignment)
    current[0] = Application(uuid4(), store=store)
    assert (
        client.post(
            f"/assignments/{assignment}/evaluations", json=command(expected_revision=2)
        ).status_code
        == 404
    )
    assert client.get(f"/processing-runs/{uid}").status_code == 404
    assert client.post(f"/processing-runs/{uid}/retry", json=command()).status_code == 404


def test_lost_evaluation_write_replays_intent_without_repeating_model_call(
    flow, document_fixture, monkeypatch
):
    client, current, store, bucket, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture)
    uid = launch(client, assignment)
    parser = ComparisonParser()
    original = store.ensure
    lost = False

    def lose(table, values):
        nonlocal lost
        result = original(table, values)
        if table is EV and not lost:
            lost = True
            raise TimeoutError("lost evaluation response")
        return result

    monkeypatch.setattr(store, "ensure", lose)
    assert worker(current, bucket, parser, store).run(uid)["status"] == "failed"
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    assert len(parser.calls) == store.count(EV) == 1
    assert not client.get(f"/evaluations/{result['evaluation']['uid']}").json()["stale"]


def test_later_document_revision_marks_comparisons_stale_without_reusing_observations(
    flow, document_fixture
):
    client, current, store, bucket, _, _, _ = flow
    assignment, docs = prepare(flow, document_fixture, "account")
    parser = ComparisonParser()
    result = worker(current, bucket, parser, store).run(launch(client, assignment))
    doc = client.get(f"/documents/{docs[0]}").json()
    assert (
        client.patch(
            f"/documents/{docs[0]}/draft",
            json=command(
                expected_revision=1,
                payload=doc["payload"],
                raw_document_refs=doc["raw_document_refs"],
            ),
        ).status_code
        == 200
    )
    assert client.get(f"/evaluations/{result['evaluation']['uid']}").json()["stale"]
    current_finding = client.get(f"/assignments/{assignment}/status").json()["findings"][-1]
    assert current_finding["status"] == "pending_review"
    assert len(parser.calls) == 1


def test_missing_or_changed_citations_never_reach_parser(flow, document_fixture):
    from src.backoffice.services.comparisons import plan

    client, current, _, _, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture)
    snapshot = current[0].evaluation_input(assignment)
    import copy

    missing = copy.deepcopy(snapshot)
    missing["documents"][0]["extraction_evidence"] = None
    request, bindings = plan(missing)
    assert request is None
    assert bindings[0]["blockers"] == [("needs_information", "COMPARISON_CITED_FACT_REQUIRED")]
    # Alter a candidate without its content checksum: it is never usable evidence.
    changed = copy.deepcopy(snapshot)
    changed["documents"][0]["extraction_evidence"]["content_sha256"] = "0" * 64
    assert plan(changed)[0] is None


def test_failed_or_missing_comparison_keeps_case_incomplete(flow, document_fixture):
    from src.backoffice.services.reconciliation import reconcile

    client, current, store, bucket, _, _, _ = flow
    assignment, _ = prepare(flow, document_fixture)
    snapshot = current[0].evaluation_input(assignment)
    # Only isolate coverage in the fixture; a comparison failure independently blocks completion.
    snapshot["policy"]["requirements"] = [snapshot["policy"]["requirements"][0]]
    snapshot["policy"]["requirements"][0]["options"][0]["required_fields"] = []
    from src.backoffice.services.comparisons import plan

    request, _ = plan(snapshot)
    parser = ComparisonParser()
    snapshot["comparison_result"] = parser.compare(request).model_dump(mode="json")
    findings, summary = reconcile(snapshot)
    assert findings[-1]["status"] == "failed" and not summary["complete"]
