"""Read-only MCP/REST parity against a verified local MetaTables API and SDK login."""

import argparse
import json
import os

from fastapi.testclient import TestClient
from mainsequence.client.utils import get_authorization_headers
from metatables import configure_local_client, get_runtime_status

from scripts.developer_session import configure_developer_session
from scripts.local_api import require_local_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.environ.get("APP_NAME"):
        raise RuntimeError("This verifier is for local development only")
    configure_developer_session()
    configure_local_client()
    source_uid = require_local_runtime(get_runtime_status())
    from api.app.main import create_app

    headers = {
        **get_authorization_headers(),
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(create_app(), headers=headers) as client:
        checked_tools = set()

        def query(name, arguments, path):
            response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            response.raise_for_status()
            result = response.json()["result"]
            if result.get("isError"):
                raise RuntimeError(f"{name} failed: {result}")
            actual = result["structuredContent"]
            rest = client.get(path)
            rest.raise_for_status()
            expected = rest.json()
            if name == "get_current_user":
                expected.pop("is_organization_admin", None)

            def without_clock(value):
                if isinstance(value, dict):
                    return {k: without_clock(v) for k, v in value.items() if k != "assessed_at"}
                if isinstance(value, list):
                    return [without_clock(v) for v in value]
                return value

            if without_clock(actual) != without_clock(expected):
                raise AssertionError(f"{name} differs from REST")
            checked_tools.add(name)
            return actual

        query("get_current_user", {}, "/me")
        query("get_person_schema", {}, "/person-schema")
        query("list_case_types", {}, "/case-types")
        query("list_cases", {"limit": 1}, "/cases?limit=1")
        sets = query("list_document_sets", {"limit": 10}, "/document-sets?limit=10")
        if not sets["items"]:
            raise RuntimeError("Publish the local catalog before running this verifier")
        policy = sets["items"][0]
        query(
            "get_document_set",
            {"key": policy["key"], "version": policy["version"]},
            f"/document-sets/{policy['key']}/versions/{policy['version']}",
        )
        people = query("search_persons", {"limit": 10}, "/persons?limit=10")
        checked_assignment = False
        for person in people["items"]:
            uid = person["uid"]
            query("get_person", {"person_uid": uid}, f"/persons/{uid}")
            query("list_person_cases", {"person_uid": uid}, f"/persons/{uid}/cases")
            query("list_person_documents", {"person_uid": uid}, f"/persons/{uid}/documents")
            query("list_person_sources", {"person_uid": uid}, f"/persons/{uid}/sources")
            assignments = query(
                "list_person_assignments", {"person_uid": uid}, f"/persons/{uid}/assignments"
            )
            if assignments["items"]:
                assignment = assignments["items"][0]["uid"]
                query(
                    "get_assignment", {"assignment_uid": assignment}, f"/assignments/{assignment}"
                )
                query(
                    "get_document_set_status",
                    {"assignment_uid": assignment},
                    f"/assignments/{assignment}/status",
                )
                query(
                    "get_missing_requirements",
                    {"assignment_uid": assignment},
                    f"/assignments/{assignment}/missing-requirements",
                )
                query("get_case", {"case_uid": assignment}, f"/cases/{assignment}")
                query(
                    "get_case_workspace", {"case_uid": assignment}, f"/cases/{assignment}/workspace"
                )
                query(
                    "get_case_reviewers", {"case_uid": assignment}, f"/cases/{assignment}/reviewers"
                )
                query(
                    "list_case_evaluations",
                    {"case_uid": assignment},
                    f"/cases/{assignment}/evaluations",
                )
                checked_assignment = True
                break
        if require_local_runtime(get_runtime_status()) != source_uid:
            raise RuntimeError("Runtime changed during verification")
    print(
        json.dumps(
            {
                "status": "passed",
                "tools": len(checked_tools),
                "assignment_queries_checked": checked_assignment,
                "local_mode": True,
                "dialect": "sqlite",
                "data_source_uid": source_uid,
                "fixture_commands": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
