"""Exercise real HTTP workflows on an explicitly verified local MetaTables runtime."""

import argparse
import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        parser.error("Integration fixtures require an explicit loopback API URL.")

    def call(method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(base + path, body, {"Content-Type": "application/json"}, method=method)
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    def mutate(path, **values):
        return call("POST", path, {"operation_key": str(uuid4()), **values})

    health = call("GET", "/healthz")
    if (
        health.get("metatables", {}).get("local_mode") is not True
        or health["metatables"].get("dialect") != "sqlite"
    ):
        raise RuntimeError("Refusing fixtures outside the verified local SQLite runtime")
    ready = call("GET", "/readyz")
    if not ready.get("can_review"):
        raise RuntimeError("This local test requires explicitly configured reviewer permission")
    person = mutate(
        "/persons",
        profile={
            "external_reference": f"local-api-verification-{uuid4()}",
            "full_name": "Alex Morgan",
            "date_of_birth": "1990-03-12",
            "employment_status": "retired",
            "residency_permit_required": False,
            "residential_address": {
                "address_line_1": "14 Example Street",
                "city": "Prague",
                "postal_code": "11000",
                "country_code": "CZ",
            },
        },
    )["uid"]
    assignment = mutate(
        f"/persons/{person}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=1,
    )
    docs = []
    for kind in (
        "national_identity_card",
        "utility_bill",
        "source_of_funds_evidence",
        "kyc_questionnaire",
    ):
        payload = json.loads(
            (
                Path(__file__).resolve().parents[1] / "tests/fixtures/documents" / f"{kind}.json"
            ).read_text()
        )
        if kind == "utility_bill":
            payload["issue_date"] = datetime.now(UTC).date().isoformat()
        if kind == "kyc_questionnaire":
            payload["employment_status"] = "retired"
        content = json.dumps(payload).encode()
        if kind == "national_identity_card":
            content += b" " * (600 * 1024)  # Exercise multiple bounded source chunks.
        upload = mutate(
            "/source-documents/uploads",
            person_uid=person,
            filename=f"{kind}.txt",
            media_type="text/plain",
            byte_count=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        chunk_size = upload["chunk_bytes"]
        for index, offset in enumerate(range(0, len(content), chunk_size)):
            call(
                "PUT",
                f"/source-documents/uploads/{upload['uid']}/chunks/{index}",
                {
                    "content_base64": base64.b64encode(
                        content[offset : offset + chunk_size]
                    ).decode()
                },
            )
        mutate(f"/source-documents/uploads/{upload['uid']}/finalize")
        doc = mutate(
            f"/persons/{person}/documents",
            document_type=kind,
            payload=payload,
            raw_document_refs=[{"raw_document_uid": upload["uid"]}],
        )
        mutate(f"/documents/{doc['uid']}/submit", expected_revision=1)
        mutate(
            f"/documents/{doc['uid']}/reviews",
            expected_revision=1,
            expected_decision_sequence=0,
            decision="accepted",
            reason="Local verification fixture checked against its raw source",
        )
        docs.append(doc["uid"])
    call(
        "PUT",
        f"/assignments/{assignment['uid']}/documents",
        {"operation_key": str(uuid4()), "expected_revision": 1, "document_uids": docs},
    )
    report = mutate(f"/assignments/{assignment['uid']}/evaluations", expected_revision=2)
    result = call("GET", f"/evaluations/{report['uid']}")
    assert result["summary"]["complete"] is True, result["findings"]
    assert result["stale"] is False
    assert len(call("GET", f"/persons/{person}/documents")["items"]) == 4
    assert call("GET", f"/persons/{person}/documents")["total_items"] == 4
    current = call("GET", f"/documents/{docs[0]}")
    call(
        "PATCH",
        f"/documents/{docs[0]}/draft",
        {
            "operation_key": str(uuid4()),
            "expected_revision": 1,
            "payload": current["payload"],
            "raw_document_refs": current["raw_document_refs"],
        },
    )
    assert call("GET", f"/documents/{docs[0]}")["accepted"] is False
    assert call("GET", f"/evaluations/{report['uid']}")["stale"] is True
    print(
        f"Verified real API workflow: person {person}, 4 uploaded/submitted/reviewed documents, complete evaluation, and stale revision detection."
    )
    print(f"Local MetaTables DataSource: {health['metatables']['data_source_uid']}")


if __name__ == "__main__":
    main()
