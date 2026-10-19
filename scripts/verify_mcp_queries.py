"""Read-only MCP/REST parity against a verified local MetaTables API and SDK login."""

import argparse
import json
import os
from uuid import uuid4

from fastapi.testclient import TestClient
from mainsequence.client.utils import get_authorization_headers
from metatables import configure_local_client, get_runtime_status

from scripts.developer_session import configure_developer_session
from scripts.local_api import require_local_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Create one labeled local person and assignment for this verification; retained for inspection.",
    )
    args = parser.parse_args()
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
            actual.pop("assessed_at", None)
            expected.pop("assessed_at", None)
            if actual != expected:
                raise AssertionError(f"{name} differs from REST")
            return actual

        query("get_current_user", {}, "/me")
        query("get_person_schema", {}, "/person-schema")
        sets = query("list_document_sets", {"limit": 10}, "/document-sets?limit=10")
        if not sets["items"]:
            raise RuntimeError("Publish the local catalog before running this verifier")
        policy = sets["items"][0]
        query(
            "get_document_set",
            {"key": policy["key"], "version": policy["version"]},
            f"/document-sets/{policy['key']}/versions/{policy['version']}",
        )
        if args.seed:
            if require_local_runtime(get_runtime_status()) != source_uid:
                raise RuntimeError("Runtime changed before fixture writes")
            response = client.post(
                "/persons",
                json={
                    "operation_key": str(uuid4()),
                    "profile": {
                        "full_name": "MCP query verification",
                        "external_reference": f"local-mcp-query-verification-{uuid4()}",
                    },
                },
            )
            response.raise_for_status()
            person_uid = response.json()["uid"]
            response = client.post(
                f"/persons/{person_uid}/document-sets",
                json={
                    "operation_key": str(uuid4()),
                    "document_set_key": policy["key"],
                    "document_set_version": policy["version"],
                },
            )
            response.raise_for_status()
        people = query("search_persons", {"limit": 10}, "/persons?limit=10")
        checked_assignment = False
        for person in people["items"]:
            uid = person["uid"]
            query("get_person", {"person_uid": uid}, f"/persons/{uid}")
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
                checked_assignment = True
                break
        if not checked_assignment:
            raise RuntimeError(
                "No accessible assignment among the first ten people; create a local fixture before verifying missing requirements"
            )
        if require_local_runtime(get_runtime_status()) != source_uid:
            raise RuntimeError("Runtime changed during verification")
    print(
        json.dumps(
            {
                "status": "passed",
                "tools": 10,
                "local_mode": True,
                "dialect": "sqlite",
                "data_source_uid": source_uid,
                "fixture_commands": 2 if args.seed else 0,
            }
        )
    )


if __name__ == "__main__":
    main()
