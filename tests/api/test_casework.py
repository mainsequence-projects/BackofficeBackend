"""Case subjects, staff responsibility and dashboard reads retain separate boundaries."""

from uuid import uuid4

from src.backoffice.services.application import Application
from tests.api.test_document_processing import flow as flow
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person, post


def test_multiple_staff_memberships_do_not_change_evidence_or_grant_review(business):
    client, current, store = business
    subject = make_person(client)
    case = post(
        client,
        f"/persons/{subject}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=1,
    )["uid"]
    owner = current[0]
    path = f"/assignments/{case}/reviewers/me"
    assert client.put(path, json=command(expected_revision=0, assigned=True)).status_code == 403
    first, second = uuid4(), uuid4()
    current[0] = Application(first, reviewer=True, store=store, actor_display_name="First reviewer")
    snapshot = current[0].evaluation_input(case)
    body = command(expected_revision=0, assigned=True)
    assert client.put(path, json=body).status_code == 200
    assert client.put(path, json=body).status_code == 200
    assert client.put(path, json=command(expected_revision=0, assigned=False)).status_code == 409
    current[0] = Application(
        second, reviewer=True, store=store, actor_display_name="Second reviewer"
    )
    assert client.put(path, json=command(expected_revision=0, assigned=True)).status_code == 200
    members = client.get(f"/assignments/{case}/reviewers").json()
    assert {r["reviewer_uid"] for r in members["items"]} == {str(first), str(second)}
    assert all(r["reviewer_uid"] != subject for r in members["items"])
    assert current[0].evaluation_input(case) == snapshot
    assert client.get("/review-queue?responsibility=mine").json()["total_items"] == 1
    assert client.get("/review-queue?responsibility=unassigned").json()["total_items"] == 0
    assert client.put(path, json=command(expected_revision=1, assigned=False)).status_code == 200
    assert client.get("/review-queue?responsibility=mine").json()["total_items"] == 0
    current[0] = Application(first, store=store)  # Membership never grants permission.
    assert client.get(f"/assignments/{case}/workspace").status_code == 404
    current[0] = owner
    view = client.get(f"/assignments/{case}/workspace").json()
    assert view["subject"]["uid"] == subject
    assert view["reviewers"]["items"][0]["reviewer_uid"] == str(first)
    assert view["workflow_state"] == "missing_evidence"


def test_queue_access_search_and_pagination(business):
    client, current, store = business
    owner = current[0]
    one = make_person(client, full_name="Case Subject One")
    for _ in range(2):
        post(
            client,
            f"/persons/{one}/document-sets",
            document_set_key="new_account_requirements",
            document_set_version=1,
        )
    current[0] = Application(uuid4(), store=store)
    two = make_person(client, full_name="Case Subject Two")
    other = post(
        client,
        f"/persons/{two}/document-sets",
        document_set_key="loan_requirements",
        document_set_version=1,
    )["uid"]
    current[0] = owner
    page = client.get("/review-queue?limit=1").json()
    assert page["total_items"] == 2 and page["has_more"]
    assert page["items"][0]["subject"]["uid"] == one
    assert client.get("/review-queue?search=Two").json()["total_items"] == 0
    assert client.get(f"/assignments/{other}/workspace").status_code == 404
    current[0] = Application(uuid4(), reviewer=True, store=store)
    assert client.get("/review-queue?set_key=loan_requirements").json()["total_items"] == 1
    assert client.get("/review-queue?search=Subject").json()["total_items"] == 3
    assert client.get("/review-queue?search=%25").json()["total_items"] == 0
    assert client.get("/review-queue?limit=21").status_code == 422
    assert client.get("/review-queue?responsibility=everyone").status_code == 422


def test_workspace_keeps_current_sources_and_excludes_stale_comparison_decisions(
    flow, document_fixture
):
    from tests.api.test_document_comparisons import ComparisonParser, launch, prepare
    from tests.api.test_document_processing import worker

    client, current, store, bucket, _, subject, _ = flow
    case, docs = prepare(flow, document_fixture)
    run = launch(client, case)
    assert worker(current, bucket, ComparisonParser(), store).run(run)["status"] == "completed"
    path = f"/assignments/{case}/workspace"
    view = client.get(path).json()
    assert view["subject"]["uid"] == subject
    assert view["workflow_state"] == "discrepancy"
    assert view["page_count"] == 2 and view["page_count_complete"]
    assert not view["latest_evaluation"]["stale"]
    for doc in view["documents"]:
        assert doc["evidence_summary"]["has_evidence"]
        assert doc["evidence_summary"]["field_count"] > 0
        assert (
            doc["evidence_summary"]["pages"][0]["source_uid"]
            == doc["raw_document_refs"][0]["raw_document_uid"]
        )
        assert "extraction_evidence" not in doc  # Fetch full reader payload only on selection.
    current[0].actor_display_name = "Case reviewer"
    assert (
        client.put(
            f"/assignments/{case}/reviewers/me", json=command(expected_revision=0, assigned=True)
        ).status_code
        == 200
    )
    assert not client.get(path).json()["latest_evaluation"]["stale"]
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
    changed = client.get(path).json()
    assert changed["latest_evaluation"]["stale"]
    assert not changed["page_count_complete"]
    assert not any(
        f["reason_code"] == "COMPARISON_RULE_FAILED" for f in changed["status"]["findings"]
    )
