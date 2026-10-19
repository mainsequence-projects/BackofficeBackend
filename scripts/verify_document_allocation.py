"""Verify allocation through installed MetaTables on an explicitly pinned local SQLite source.

Synthetic private fixtures and controlled bucket/parser adapters; no live extraction,
cloud bucket writes, hosted database writes or production deployment are performed.
"""

import argparse
import hashlib
import json
from uuid import UUID, uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uid", required=True, type=UUID)
    parser.add_argument(
        "--run-uid", type=UUID, help="Read and verify an existing run in a fresh process"
    )
    args = parser.parse_args()
    from scripts.developer_session import configure_developer_session

    configure_developer_session()
    from metatables import configure_local_client, get_runtime_status

    from scripts.local_api import require_local_runtime

    configure_local_client()
    source_uid = require_local_runtime(get_runtime_status())
    if source_uid != str(args.source_uid):
        raise RuntimeError("Unexpected local SQLite source; refusing writes")
    from pathlib import Path

    from mainsequence.client import User

    from src.backoffice.processing import allocation
    from src.backoffice.processing.allocation_contracts import IntakeUpload
    from src.backoffice.processing.workflow import Worker
    from src.backoffice.services.application import Application
    from src.backoffice.services.cases import create
    from src.backoffice.services.contracts import CreateCase, CreatePerson
    from tests.api.test_document_processing import Bucket, Dispatcher, Parser, png

    user = User.get_authenticated_user_details()
    app = Application(user.uid)
    if args.run_uid:
        outcome = allocation.view(app, allocation.get(app, args.run_uid))
        assert outcome["status"] == "completed" and outcome["target_count"] == 2, outcome
        assert all(
            app.evaluation(t["evaluation_uid"])["stale"] is False for t in outcome["targets"]
        )
        print(
            json.dumps(
                {
                    "result": "retained_allocation_verified",
                    "run_uid": str(args.run_uid),
                    "source_uid": source_uid,
                }
            )
        )
        return
    profile = {
        "full_name": f"Allocation fixture {uuid4()}",
        "date_of_birth": "1990-03-12",
        "employment_status": "retired",
        "residency_permit_required": False,
    }
    person = app.create_person(CreatePerson(operation_key=uuid4(), profile=profile))["uid"]
    for kind, family in [
        ("account_opening", "new_account_requirements"),
        ("new_loan", "loan_requirements"),
    ]:
        create(
            app,
            person,
            CreateCase(
                operation_key=uuid4(),
                subject_uid=person,
                case_type_key=kind,
                document_set_key=family,
                document_set_version=1,
            ),
        )
    content = png()
    bucket, dispatcher = Bucket(), Dispatcher()
    payload = json.loads(Path("tests/fixtures/documents/passport.json").read_text())
    payload.update(full_name=profile["full_name"], mrz_lines=["EXAMPLE"])
    provider = Parser(payload)
    # Real directory lookup on the requester; a trusted processor is confined to this local test.
    worker_app = Application(user.uid, parsing_processor=True)
    started = allocation.upload(
        app,
        IntakeUpload(
            operation_key=uuid4(),
            filename="allocation-fixture.png",
            media_type="image/png",
            byte_count=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        ),
        content,
        bucket=bucket,
        dispatcher=dispatcher,
    )
    outcome = Worker(worker_app, bucket=bucket, parser=provider).run(started["uid"])
    assert outcome["status"] == "completed" and outcome["target_count"] == 2, outcome
    assert all(t["status"] == "completed" for t in outcome["targets"]), outcome
    assert len(provider.extractions) == len(provider.classifications) == 1
    assert require_local_runtime(get_runtime_status()) == source_uid
    print(
        json.dumps(
            {
                "result": "passed",
                "source_uid": source_uid,
                "run_uid": outcome["uid"],
                "subject_uid": person,
                "document_uid": outcome["document"]["uid"],
                "cases": outcome["target_count"],
                "provider": "controlled fixture",
                "requester_directory": "live verified lookup",
            }
        )
    )


if __name__ == "__main__":
    main()
