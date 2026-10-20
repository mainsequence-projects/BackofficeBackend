"""Upgrade policy catalogs without rewriting existing rows or case bindings."""

import json

import pytest

from src.backoffice.policies import document_set_catalog, policy_definition
from src.backoffice.services import application
from src.backoffice.services.application import SETS, publish_catalog
from src.backoffice.services.cases import BINDINGS
from tests.api.test_workflows import SQLStorage
from tests.models.test_policy_versions import SNAPSHOTS


def test_publish_adds_new_policy_versions_and_preserves_published_rows(monkeypatch):
    catalog = document_set_catalog()
    historical = tuple(
        policy
        for policy in catalog
        if (policy.key, policy.version)
        not in {("new_account_requirements", 6), ("loan_requirements", 5), ("loan_requirements", 6)}
    )
    with monkeypatch.context() as patch:
        patch.setattr(application, "document_set_catalog", lambda: historical)
        store = SQLStorage()
    try:
        existing = store.rows(SETS)
        assert len(existing) == 9
        for path in SNAPSHOTS.glob("*.json"):
            expected = json.loads(path.read_text())
            assert (
                store.one(SETS, set_key=expected["key"], version=expected["version"])["definition"]
                == expected
            )
        publish_catalog(store)
        assert store.count(SETS) == store.count(BINDINGS) == 12
        for row in existing:
            assert store.one(SETS, set_key=row["set_key"], version=row["version"]) == row
        for policy in catalog:
            assert store.one(SETS, set_key=policy.key, version=policy.version)[
                "definition"
            ] == policy_definition(policy)
        after_publish = store.rows(SETS)
        publish_catalog(store)
        assert store.rows(SETS) == after_publish
    finally:
        store.engine.dispose()


def test_publisher_still_rejects_changes_to_existing_policy(monkeypatch):
    store = SQLStorage()
    try:
        existing = store.one(SETS, set_key="new_account_requirements", version=4)
        changed = document_set_catalog()
        next(
            p for p in changed if p.key == "new_account_requirements" and p.version == 4
        ).name = "An incompatible redefinition"
        monkeypatch.setattr(application, "document_set_catalog", lambda: changed)
        with pytest.raises(RuntimeError, match="authored immutable contract"):
            publish_catalog(store)
        assert store.one(SETS, set_key="new_account_requirements", version=4) == existing
    finally:
        store.engine.dispose()
