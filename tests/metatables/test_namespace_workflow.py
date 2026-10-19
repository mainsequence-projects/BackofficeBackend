"""Deployment and namespace invariants across authored tables, Job and copied guidance."""

import ast
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from scripts import migrate_backoffice
from src.backoffice.migrations import BackofficeAlembicVersion, migration
from src.backoffice.services import application
from src.backoffice.tables import metatable_models

ROOT = Path(__file__).resolve().parents[2]


def test_every_provider_table_and_registry_register_in_the_application_namespace():
    assert migration.migration_namespace == "backoffice"
    assert tuple(migration.metatable_models) == metatable_models()
    source = str(uuid4())
    requests = [
        model.build_registration_request(data_source_uid=source) for model in metatable_models()
    ]
    requests.append(
        BackofficeAlembicVersion.build_registration_request(
            data_source_uid=source,
            migration_package=migration.package,
            migration_namespace=migration.migration_namespace,
        )
    )
    assert len(requests) == 20
    assert {request.namespace for request in requests} == {"backoffice"}
    assert len({request.identifier for request in requests}) == 20


def test_deployment_requires_migrations_before_direct_consumers_and_platform_reader_access():
    workflow = yaml.safe_load((ROOT / ".mainsequence/workflows/backoffice.yaml").read_text())
    assert workflow["api_version"] == "3.0.0"
    resources = {resource["key"]: resource for resource in workflow["resources"]}
    steps = workflow["execution"]["steps"]
    job = resources[steps["migrate"]["run_job"]]
    assert job["kind"] == "job"
    assert job["spec"]["execution_path"] == "scripts/migrate_backoffice.py"
    assert steps["migrate"]["needs"] == ["image"]
    assert steps["migrate"]["image_from"] == "image"
    # The helper consumes the API through MCP and must not receive table access.
    # Its separate deployment chain and restricted grant are checked in tests/agent.
    consumers = {key for key, value in resources.items() if value["kind"] == "fastapi"}
    assert consumers
    for key in {*consumers, job["key"]}:
        assert {"repository": "MetaTables", "policy": "reader"} in resources[key]["access"][
            "branches"
        ]
    for key in consumers:
        deployments = [step for step in steps.values() if step.get("deploy") == key]
        assert len(deployments) == 1
        assert "migrate" in deployments[0]["needs"]
        assert deployments[0]["image_from"] == "image"


def test_migration_job_publishes_only_after_success_and_never_grants_roles(monkeypatch):
    events = []
    monkeypatch.setattr(
        migrate_backoffice,
        "upgrade_application",
        lambda provider: (
            events.append(("migration", provider))
            or {"migrated": False, "revision": "backoffice_0002", "data_source_uid": str(uuid4())}
        ),
    )
    monkeypatch.setattr(application, "publish_catalog", lambda: events.append(("catalog", None)))
    migrate_backoffice.main()
    assert events == [("migration", "src.backoffice.migrations:migration"), ("catalog", None)]
    events.clear()

    def failed(provider):
        raise RuntimeError("Namespace access denied")

    monkeypatch.setattr(migrate_backoffice, "upgrade_application", failed)
    with pytest.raises(RuntimeError, match="Namespace access denied"):
        migrate_backoffice.main()
    assert events == []
    tree = ast.parse((ROOT / "scripts/migrate_backoffice.py").read_text())
    called = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(func, ast.Attribute)
        and func.attr in {"grant_role", "revoke_role", "attach_policy"}
        for func in called
    )
    assert not any(
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "Namespace"
        and func.attr == "create"
        for func in called
    )


def test_copied_metatables_skills_match_the_installed_client():
    root = ROOT / ".agents/skills/metatables"
    sentinel = dict(
        line.split("=", 1)
        for line in (root / "PINNED_FROM.txt").read_text().splitlines()
        if "=" in line
    )
    assert sentinel["library_name"] == "mainsequence-metatable"
    assert sentinel["namespace"] == "metatables"
    assert sentinel["pinned_version"] == version("mainsequence-metatable")
    import metatables

    packaged = Path(metatables.__file__).resolve().parent / "_client_skills"
    sources = {path.relative_to(packaged): path for path in packaged.rglob("*") if path.is_file()}
    copied = {
        path.relative_to(root): path
        for path in root.rglob("*")
        if path.is_file() and path.name != "PINNED_FROM.txt"
    }
    assert sources.keys() == copied.keys()
    for relative, source in sources.items():
        assert source.read_bytes() == copied[relative].read_bytes(), str(relative)
