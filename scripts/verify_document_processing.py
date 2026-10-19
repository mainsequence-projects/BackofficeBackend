"""Exercise workflow persistence on explicitly selected local SQLite with controlled providers.

The bucket and parser are deterministic test doubles; this does not claim live parser
availability. Identifiable synthetic fixtures remain in the isolated local runtime.
"""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uid", required=True, type=UUID)
    parser.add_argument(
        "--verify-run-uid",
        action="append",
        type=UUID,
        default=[],
        help="Read retained evidence in a fresh process without creating fixtures.",
    )
    args = parser.parse_args()
    from metatables import configure_local_client, get_runtime_status

    from scripts.developer_session import configure_developer_session
    from scripts.local_api import require_local_runtime

    configure_developer_session()
    configure_local_client()
    source_uid = require_local_runtime(get_runtime_status())
    if source_uid != str(args.source_uid):
        raise RuntimeError("Refusing writes to an unexpected local source")
    from mainsequence.client import User

    from src.backoffice.processing.workflow import BucketUpload, Worker, upload_and_start
    from src.backoffice.services.application import Application
    from src.backoffice.services.contracts import CreatePerson, UpdateParsingPolicy
    from tests.api.test_document_processing import Bucket, Dispatcher, Parser, png

    user = User.get_authenticated_user_details()
    if user.is_organization_admin is not True:
        raise RuntimeError("Policy verification requires an authenticated organization admin")
    bucket, dispatcher = Bucket(), Dispatcher()
    app = Application(user.uid, organization_admin=True, bucket=bucket)
    if args.verify_run_uid:
        from src.backoffice.services.application import DR, RUN, canonical
        from src.backoffice.services.extraction_evidence import evidence_view
        from src.backoffice.tables.evidence import FieldEvidenceRecord

        for uid in args.verify_run_uid:
            run = app.required(RUN, uid=uid)
            document = run["result"]["document"]
            saved = evidence_view(app, document["uid"], document["revision"])["evidence"]
            digest = saved.pop("content_sha256")
            assert hashlib.sha256(canonical(saved).encode()).hexdigest() == digest
            assert saved["extraction"]["contract_version"] == 2
            row = app.required(DR, document_uid=document["uid"], revision=document["revision"])
            fields = FieldEvidenceRecord.__table__
            assert app.db.rows(fields, fields.c.revision_uid == UUID(row["uid"]), limit=1)
        print(
            json.dumps(
                {
                    "result": "retained_evidence_verified",
                    "source_uid": source_uid,
                    "runs": [str(uid) for uid in args.verify_run_uid],
                }
            )
        )
        return
    settings = app.parsing_settings("passport")
    app.update_parsing_settings(
        UpdateParsingPolicy(
            operation_key=uuid4(),
            document_type="passport",
            expected_revision=settings["revision"],
            automatic_acceptance_enabled=True,
            acceptance_threshold_percent="60",
        )
    )
    person = app.create_person(
        CreatePerson(
            operation_key=uuid4(),
            profile={
                "full_name": "Synthetic extraction verification",
                "date_of_birth": "1990-03-12",
                "employment_status": "retired",
                "residency_permit_required": False,
                "residential_address": {
                    "address_line_1": "1 Fixture Street",
                    "city": "Prague",
                    "postal_code": "11000",
                    "country_code": "CZ",
                },
            },
        )
    )
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "tests/fixtures/documents/passport.json").read_text()
    )
    content = png()
    outcomes = []
    for confidence, decision in [(0.6, "accepted"), (0.59999, "needs_review")]:
        adapter = Parser(payload, confidence=confidence)
        command = BucketUpload(
            operation_key=uuid4(),
            person_uid=person["uid"],
            filename="synthetic-verification.png",
            media_type="image/png",
            byte_count=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        run = upload_and_start(app, command, content, bucket=bucket, dispatcher=dispatcher)
        worker = Worker(app, parser=adapter, bucket=bucket)
        result = worker.run(run["uid"])
        assert result["status"] == "completed", result
        assert result["completion"]["decision"] == decision, result
        assert Worker(app, parser=adapter, bucket=bucket).run(run["uid"]) == result
        assert len(adapter.classifications) == len(adapter.extractions) == 1
        assert app.document(result["document"]["uid"])["accepted"] is (decision == "accepted")
        from src.backoffice.services.extraction_evidence import evidence_view

        evidence = evidence_view(app, result["document"]["uid"], 1)["evidence"]
        assert evidence["run_uid"] == run["uid"]
        assert evidence["extraction"]["field_evidence"]
        outcomes.append({"run_uid": run["uid"], "decision": decision})
    print(
        json.dumps(
            {
                "result": "passed",
                "local_source_uid": source_uid,
                "person_uid": person["uid"],
                "providers": "controlled",
                "outcomes": outcomes,
            }
        )
    )


if __name__ == "__main__":
    main()
