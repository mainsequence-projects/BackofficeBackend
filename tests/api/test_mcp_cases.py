"""Case building over authenticated MCP, sharing REST storage and real durable workers."""

from uuid import uuid4

import pytest

from api.app import main
from src.backoffice.processing import workflow
from src.backoffice.services.application import EV, A, Application, P
from src.backoffice.services.contracts import UpdateParsingPolicy
from tests.api.test_document_comparisons import ComparisonParser
from tests.api.test_document_processing import Bucket, Dispatcher, Parser, png
from tests.api.test_mcp_queries import HEADERS, tool
from tests.api.test_mcp_queries import mcp_client as mcp_client
from tests.api.test_workflows import command, make_person, post


def ok(client, name, arguments=None, **kwargs):
    result = tool(client, name, arguments, **kwargs)
    assert not result.get("isError"), result
    return result["structuredContent"]


def write(client, name, body):
    return ok(client, name, {"command": body})


def error(client, name, arguments, status, **kwargs):
    result = tool(client, name, arguments, **kwargs)
    assert result["isError"], result
    assert result["structuredContent"]["error"]["status"] == status, result
    return result


def build(client, person, kind="account_opening", version=1):
    return write(
        client,
        "create_case",
        command(
            subject_uid=person,
            case_type_key=kind,
            document_set_key="loan_requirements"
            if kind == "new_loan"
            else "new_account_requirements",
            document_set_version=version,
        ),
    )["uid"]


def test_build_person_multiple_cases_link_and_evaluate(mcp_client):
    client, store, owner = mcp_client
    body = command(profile={"full_name": "Case Subject"})
    person = write(client, "create_person", body)["uid"]
    assert write(client, "create_person", body)["uid"] == person
    assert store.one(P, uid=person)["created_by"] == owner
    cases = [build(client, person, kind) for kind in ("account_opening", "new_loan")]
    assert {
        c["uid"] for c in ok(client, "list_person_cases", {"person_uid": person})["items"]
    } == set(cases)
    assert store.count(A) == 2
    wrong = command(
        subject_uid=person,
        case_type_key="new_loan",
        document_set_key="new_account_requirements",
        document_set_version=1,
    )
    error(client, "create_case", {"command": wrong}, 422)
    doc = post(client, f"/persons/{person}/documents", document_type="passport")["uid"]
    body = command(case_uid=cases[0], expected_revision=1, document_uids=[doc])
    assert write(client, "link_case_documents", body)["revision"] == 2
    assert write(client, "link_case_documents", body)["revision"] == 2
    error(client, "link_case_documents", {"command": {**body, "case_uid": cases[1]}}, 409)
    error(
        client,
        "link_case_documents",
        {"command": command(case_uid=cases[0], expected_revision=1, document_uids=[doc])},
        409,
    )
    error(
        client,
        "link_case_documents",
        {"command": command(case_uid=cases[0], expected_revision=2, document_uids=[])},
        422,
    )
    foreign_person = make_person(client)
    foreign_doc = post(client, f"/persons/{foreign_person}/documents", document_type="passport")[
        "uid"
    ]
    error(
        client,
        "link_case_documents",
        {
            "command": command(
                case_uid=cases[0], expected_revision=2, document_uids=[doc, foreign_doc]
            )
        },
        422,
    )
    evaluation_body = command(case_uid=cases[0], expected_revision=2)
    evaluated = write(client, "evaluate_case", evaluation_body)
    assert write(client, "evaluate_case", evaluation_body) == evaluated
    assert store.count(EV) == 1
    saved = ok(client, "get_evaluation", {"evaluation_uid": evaluated["uid"]})
    assert not saved["stale"] and not saved["summary"]["complete"]
    assert saved == client.get(f"/evaluations/{evaluated['uid']}").json()
    assert len(ok(client, "list_case_evaluations", {"case_uid": cases[0]})["items"]) == 1
    # Match revisions so the idempotency collision really tests target binding.
    write(
        client,
        "link_case_documents",
        command(case_uid=cases[1], expected_revision=1, document_uids=[doc]),
    )
    error(client, "evaluate_case", {"command": {**evaluation_body, "case_uid": cases[1]}}, 409)
    assert (
        ok(client, "get_document", {"document_uid": doc, "revision": 1})
        == client.get(f"/documents/{doc}/revisions/1").json()
    )
    missing = ok(client, "get_missing_requirements", {"assignment_uid": cases[0]})
    assert missing["findings"] and not missing["summary"]["complete"]


def test_authorized_reviewer_can_only_change_own_membership(mcp_client, monkeypatch):
    client, _, owner = mcp_client
    person = make_person(client)
    uid, other = build(client, person), build(client, person)
    body = command(case_uid=uid, expected_revision=0, assigned=True)
    error(client, "set_my_case_membership", {"command": body}, 403)
    monkeypatch.setenv("BACKOFFICE_REVIEWER_UIDS", owner)
    assert ok(client, "get_case_reviewers", {"case_uid": uid})["my_revision"] == 0
    membership = write(client, "set_my_case_membership", body)
    assert membership["reviewer_uid"] == owner and membership["active"] is True
    assert write(client, "set_my_case_membership", body) == membership
    error(client, "set_my_case_membership", {"command": {**body, "case_uid": other}}, 409)
    observed = ok(client, "get_case_reviewers", {"case_uid": uid})
    assert observed["my_revision"] == 1
    assert ok(client, "get_case", {"case_uid": uid})["revision"] == 1
    write(
        client, "set_my_case_membership", command(case_uid=uid, expected_revision=1, assigned=False)
    )
    assert not ok(client, "get_case_reviewers", {"case_uid": uid})["assigned_to_me"]
    assert tool(
        client, "set_my_case_membership", {"command": {**body, "reviewer_uid": str(uuid4())}}
    )["isError"]


def test_case_write_identity_and_strict_commands(mcp_client):
    client, store, _ = mcp_client
    person = make_person(client)
    case = build(client, person)
    stranger = {**HEADERS, "Authorization": f"Bearer {uuid4()}"}
    for name, args in [
        ("get_case", {"case_uid": case}),
        ("get_case_workspace", {"case_uid": case}),
        ("get_case_reviewers", {"case_uid": case}),
        ("list_person_cases", {"person_uid": person}),
        ("list_person_sources", {"person_uid": person}),
        ("list_person_documents", {"person_uid": person}),
        ("list_case_evaluations", {"case_uid": case}),
        (
            "link_case_documents",
            {"command": command(case_uid=case, expected_revision=1, document_uids=[])},
        ),
        ("evaluate_case", {"command": command(case_uid=case, expected_revision=1)}),
        (
            "create_case",
            {
                "command": command(
                    subject_uid=person,
                    case_type_key="account_opening",
                    document_set_key="new_account_requirements",
                    document_set_version=1,
                )
            },
        ),
    ]:
        error(client, name, args, 404, headers=stranger)
    assert not ok(client, "list_cases", headers=stranger)["items"]
    writes = []
    original = store.execute

    def read_only(statement, operation="select"):
        if operation != "select":
            writes.append(operation)
        return original(statement, operation)

    store.execute = read_only
    for bad in [True, "1", 1.0, 0]:
        assert tool(
            client, "evaluate_case", {"command": command(case_uid=case, expected_revision=bad)}
        )["isError"]
        assert tool(
            client,
            "create_case",
            {
                "command": command(
                    subject_uid=person,
                    case_type_key="account_opening",
                    document_set_key="new_account_requirements",
                    document_set_version=bad,
                )
            },
        )["isError"]
    assert tool(
        client,
        "create_person",
        {"command": command(profile={"full_name": "Bad"}, actor_uid=str(uuid4()))},
    )["isError"]
    assert tool(
        client,
        "set_my_case_membership",
        {"command": command(case_uid=case, expected_revision=0, assigned="true")},
    )["isError"]
    assert not writes


@pytest.fixture
def processing(mcp_client, monkeypatch):
    client, store, owner = mcp_client
    bucket, dispatcher = Bucket(), Dispatcher()
    # The MCP factory captured this function; patch its implementation class.
    monkeypatch.setattr(main, "MainSequenceDispatcher", lambda: dispatcher)
    client.app.dependency_overrides[main.processing_bucket] = lambda: bucket
    worker_app = Application(uuid4(), parsing_processor=True, store=store, bucket=bucket)
    return client, store, owner, bucket, dispatcher, worker_app


@pytest.mark.parametrize("score,decision", [(0.60, "accepted"), (0.59, "needs_review")])
def test_existing_source_extraction_acceptance_link_and_case_comparison(
    processing, document_fixture, score, decision
):
    client, store, owner, bucket, dispatcher, worker_app = processing
    person = write(client, "create_person", command(profile={"full_name": "Alex Morgan"}))["uid"]
    # Policy is administrator-owned setup, never a helper mutation.
    Application(owner, store=store, organization_admin=True).update_parsing_settings(
        UpdateParsingPolicy(
            operation_key=uuid4(),
            document_type="passport",
            expected_revision=0,
            automatic_acceptance_enabled=True,
            acceptance_threshold_percent="60",
        )
    )
    case = build(client, person, version=6)
    source = client.post(
        "/source-documents/bucket-uploads",
        data={"person_uid": person, "operation_key": str(uuid4())},
        files={"file": ("passport.png", png(), "image/png")},
    )
    assert source.status_code == 201, source.text
    source_uid = source.json()["uid"]
    args = {"source_uid": source_uid, "command": command()}
    run = ok(client, "process_source_document", args)
    assert ok(client, "process_source_document", args)["uid"] == run["uid"]
    stranger = {**HEADERS, "Authorization": f"Bearer {uuid4()}"}
    error(client, "process_source_document", args, 404, headers=stranger)
    error(client, "get_processing_run", {"run_uid": run["uid"]}, 404, headers=stranger)
    error(
        client,
        "retry_processing_run",
        {"run_uid": run["uid"], "command": command()},
        404,
        headers=stranger,
    )
    parser = Parser(document_fixture("passport"), confidence=score)
    parser.fail_extraction = True
    failed = workflow.Worker(worker_app, parser=parser, bucket=bucket).run(run["uid"])
    assert failed["status"] == "failed"
    assert "private" not in str(ok(client, "get_processing_run", {"run_uid": run["uid"]}))
    retry_args = {"run_uid": run["uid"], "command": command()}
    ok(client, "retry_processing_run", retry_args)
    parser.fail_extraction = False
    done = workflow.Worker(worker_app, parser=parser, bucket=bucket).run(run["uid"])
    assert done["status"] == "completed", done
    assert done["completion"]["decision"] == decision
    assert len(parser.classifications) == 1
    doc_uid = done["document"]["uid"]
    doc = ok(client, "get_document", {"document_uid": doc_uid})
    assert doc["accepted"] is (decision == "accepted")
    evidence = ok(
        client, "get_document_extraction_evidence", {"document_uid": doc_uid, "revision": 1}
    )
    assert evidence == client.get(f"/documents/{doc_uid}/revisions/1/extraction-evidence").json()
    error(client, "get_document", {"document_uid": doc_uid}, 404, headers=stranger)
    error(
        client,
        "get_document_extraction_evidence",
        {"document_uid": doc_uid, "revision": 1},
        404,
        headers=stranger,
    )
    assert (
        ok(client, "get_processing_run", {"run_uid": run["uid"]})
        == client.get(f"/processing-runs/{run['uid']}").json()
    )
    write(
        client,
        "link_case_documents",
        command(case_uid=case, expected_revision=1, document_uids=[doc_uid]),
    )
    body = command(case_uid=case, expected_revision=2)
    evaluation_run = write(client, "evaluate_case", body)["processing_run_uid"]
    other_case = build(client, person, version=6)
    error(client, "evaluate_case", {"command": {**body, "case_uid": other_case}}, 409)
    comparison = workflow.Worker(worker_app, parser=ComparisonParser(), bucket=bucket).run(
        evaluation_run
    )
    assert comparison["status"] == "completed", comparison
    saved = ok(client, "get_evaluation", {"evaluation_uid": comparison["evaluation"]["uid"]})
    assert not saved["stale"]
    error(client, "get_evaluation", {"evaluation_uid": saved["uid"]}, 404, headers=stranger)
    assert write(client, "evaluate_case", body)["uid"] == saved["uid"]
    assert ok(client, "get_document", {"document_uid": doc_uid})["accepted"] is (
        decision == "accepted"
    )
    assert dispatcher.calls


@pytest.mark.parametrize(
    "name", ["create_case", "link_case_documents", "evaluate_case", "set_my_case_membership"]
)
def test_mcp_replays_interrupted_case_mutations_without_duplicates(mcp_client, monkeypatch, name):
    client, store, owner = mcp_client
    person = make_person(client)
    uid = build(client, person)
    monkeypatch.setenv("BACKOFFICE_REVIEWER_UIDS", owner)
    bodies = {
        "create_case": command(
            subject_uid=person,
            case_type_key="new_loan",
            document_set_key="loan_requirements",
            document_set_version=1,
        ),
        "link_case_documents": command(case_uid=uid, expected_revision=1, document_uids=[]),
        "evaluate_case": command(case_uid=uid, expected_revision=1),
        "set_my_case_membership": command(case_uid=uid, expected_revision=0, assigned=True),
    }
    body = bodies[name]
    store.fail_after_write = 3
    interrupted = tool(client, name, {"command": body})
    assert interrupted["isError"]
    assert "Response lost" not in str(interrupted)  # SDK sanitizes unexpected storage errors.
    recovered = write(client, name, body)
    assert write(client, name, body) == recovered
    assert store.count(A) == (2 if name == "create_case" else 1)
    assert store.count(EV) == (1 if name == "evaluate_case" else 0)
    assert ok(client, "get_case", {"case_uid": uid})["revision"] == (
        2 if name == "link_case_documents" else 1
    )
