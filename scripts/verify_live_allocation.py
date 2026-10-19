"""Verify the real local API -> bucket -> deployed parser -> worker -> cases path.

No parser/bucket overrides. Supply existing local subjects/cases and a synthetic
example document. The local source guard runs before uploads. --run-uid verifies
an existing result without uploading or retrying it.
"""

import argparse
import hashlib
import json
import mimetypes
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-origin", default="http://127.0.0.1:28641")
    parser.add_argument("--expected-source-uid", required=True, type=UUID)
    parser.add_argument("--subject-uid", required=True, type=UUID)
    parser.add_argument("--case-uid", required=True, type=UUID, action="append")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--run-uid", type=UUID)
    args = parser.parse_args()
    url = urlsplit(args.api_origin)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"} or url.path:
        parser.error("Use the explicit loopback developer API origin")

    def get(path):
        response = requests.get(args.api_origin + path, timeout=30)
        response.raise_for_status()
        return response.json()

    def guard():
        state = get("/healthz")["metatables"]
        assert state == {
            "local_mode": True,
            "dialect": "sqlite",
            "data_source_uid": str(args.expected_source_uid),
        }, "Unexpected database; refusing live verification"

    guard()
    uid = args.run_uid
    if uid is None:
        with args.file.open("rb") as file:
            response = requests.post(
                args.api_origin + "/document-intakes",
                data={"operation_key": str(uuid4())},
                files={
                    "file": (
                        args.file.name,
                        file,
                        mimetypes.guess_type(args.file.name)[0] or "application/octet-stream",
                    )
                },
                timeout=120,
            )
        response.raise_for_status()
        uid = UUID(response.json()["uid"])
    previous = None
    deadline = time.monotonic() + 300
    while True:
        result = get(f"/document-allocations/{uid}")
        progress = result["status"], result["stage"]
        if progress != previous:
            print(
                json.dumps({"run_uid": str(uid), "status": progress[0], "stage": progress[1]}),
                flush=True,
            )
            previous = progress
        if result["status"] in {"completed", "needs_input", "failed"}:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Processing did not finish within the verification window")
        time.sleep(3)
    assert result["status"] == "completed", {
        "status": result["status"],
        "stage": result["stage"],
        "error_code": result["error_code"],
    }
    assert result["subject_uid"] == str(args.subject_uid)
    targets = list(result["targets"])
    while len(targets) < result["target_count"]:
        page = get(f"/document-allocations/{uid}?limit=100&offset={len(targets)}")
        assert page["targets"], "Incomplete target pagination"
        targets.extend(page["targets"])
    assert {t["case_uid"] for t in targets} == {str(uid) for uid in args.case_uid}
    document = get(f"/documents/{result['document']['uid']}")
    for target in targets:
        assert target["status"] == "completed", target["status"]
        case = get(f"/cases/{target['case_uid']}")
        assert case["document_uids"].count(document["uid"]) == 1
        evaluation = get(f"/evaluations/{target['evaluation_uid']}")
        assert evaluation["stale"] is False
    assert len(document["raw_document_refs"]) == 1
    source_uid = document["raw_document_refs"][0]["raw_document_uid"]
    response = requests.get(args.api_origin + f"/source-documents/{source_uid}/content", timeout=60)
    response.raise_for_status()
    assert (
        hashlib.sha256(response.content).digest() == hashlib.sha256(args.file.read_bytes()).digest()
    )
    guard()
    print(
        json.dumps(
            {
                "verified": True,
                "run_uid": str(uid),
                "document_uid": document["uid"],
                "cases_evaluated": len(targets),
                "bucket_bytes_verified": True,
                "document_decision": result["completion"]["decision"],
                "decision_reason": result["completion"]["reason_code"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
