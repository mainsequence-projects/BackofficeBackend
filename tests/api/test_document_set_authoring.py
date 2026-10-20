"""Admin-created document sets retain immutable definitions and exact case bindings."""

from copy import deepcopy
from uuid import uuid4

import pytest

from src.backoffice.services.application import SETS, Application
from src.backoffice.services.cases import BINDINGS
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person


def request(key=None):
    return command(
        definition={
            "key": key or f"local_set_{uuid4().hex}",
            "version": 1,
            "name": "Business onboarding evidence",
            "description": "A reusable custom evidence set.",
            "requirements": [
                {
                    "key": "identity",
                    "description": "Evidence identifying the subject.",
                    "options": [{"document_type": "national_identity_card", "schema_version": 3}],
                }
            ],
        },
        case_type_keys=["document_review"],
    )


def admin(current):
    previous = current[0]
    current[0] = Application(previous.actor, organization_admin=True, store=previous.db)


def test_admin_create_is_published_usable_and_immutable(business):
    client, current, store = business
    admin(current)
    before = store.rows(SETS)
    payload = request()
    response = client.post("/admin/document-sets", json=payload)
    assert response.status_code == 201, response.text
    policy = response.json()
    key = policy["key"]
    assert client.get(f"/document-sets/{key}/versions/1").json() == policy
    assert any(p["key"] == key for p in client.get("/document-sets").json()["items"])
    assert store.one(BINDINGS, case_type_key="document_review", set_key=key, set_version=1)
    assert any(
        p["key"] == key
        for t in client.get("/case-types").json()["items"]
        if t["key"] == "document_review"
        for p in t["document_sets"]
    )
    assert client.post("/admin/document-sets", json=payload).json() == policy
    conflicting = deepcopy(payload)
    conflicting["operation_key"] = str(uuid4())
    conflicting["definition"]["description"] = "Attempted replacement"
    assert client.post("/admin/document-sets", json=conflicting).status_code == 409
    assert client.get(f"/document-sets/{key}/versions/1").json() == policy
    subject = make_person(client)
    case = client.post(
        "/cases",
        json=command(
            subject_uid=subject,
            case_type_key="document_review",
            document_set_key=key,
            document_set_version=1,
        ),
    )
    assert case.status_code == 201, case.text
    detail = client.get(f"/cases/{case.json()['uid']}").json()
    assert detail["document_set_key"] == key
    assert detail["document_set_version"] == 1
    for row in before:
        assert store.one(SETS, set_key=row["set_key"], version=row["version"]) == row


def test_non_admin_cannot_create_even_with_reviewer_rights(business):
    client, current, store = business
    current[0] = Application(current[0].actor, reviewer=True, store=store)
    count = store.count(SETS)
    response = client.post("/admin/document-sets", json=request())
    assert response.status_code == 403
    assert store.count(SETS) == count


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(case_type_keys=[]),
        lambda p: p.update(case_type_keys=["nonexistent"]),
        lambda p: p["definition"].update(version=2),
        lambda p: p["definition"].update(key="../invalid"),
        lambda p: p["definition"].update(requirements=[]),
        lambda p: p["definition"]["requirements"][0]["options"][0].update(
            required_fields=["unknown_field"]
        ),
        lambda p: p["definition"]["requirements"][0]["options"][0].update(schema_version=999),
    ],
)
def test_invalid_definitions_never_publish(business, mutation):
    client, current, store = business
    admin(current)
    count = store.count(SETS)
    payload = request()
    mutation(payload)
    response = client.post("/admin/document-sets", json=payload)
    assert response.status_code == 422, response.text
    assert store.count(SETS) == count


def test_ambiguous_write_retry_recovers_original_definition(business):
    client, current, store = business
    admin(current)
    payload = request()
    store.fail_after_write = 3
    with pytest.raises(TimeoutError):
        client.post("/admin/document-sets", json=payload)
    response = client.post("/admin/document-sets", json=payload)
    assert response.status_code == 201, response.text
    assert store.count(SETS, SETS.c.set_key == payload["definition"]["key"]) == 1
    assert store.one(
        BINDINGS,
        case_type_key="document_review",
        set_key=payload["definition"]["key"],
        set_version=1,
    )
