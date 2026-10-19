"""Verify shared comparison persistence through an explicitly selected local MetaTables API.

Uses synthetic evidence and controlled providers. Never selects or writes a hosted source.
"""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source-uid", required=True, type=UUID)
    cli.add_argument("--verify-evaluation-uid", action="append", type=UUID, default=[])
    args = cli.parse_args()
    from metatables import configure_local_client, get_runtime_status

    from scripts.developer_session import configure_developer_session
    from scripts.local_api import require_local_runtime

    configure_developer_session()
    configure_local_client()
    uid = require_local_runtime(get_runtime_status())
    if uid != str(args.source_uid):
        raise RuntimeError("Refusing unexpected local source")
    from mainsequence.client import User

    from src.backoffice.processing.comparison_contracts import CompareDocumentsResponse
    from src.backoffice.services.application import Application, publish_catalog
    from src.backoffice.services.comparisons import plan

    user = User.get_authenticated_user_details()
    if user.is_organization_admin is not True:
        raise RuntimeError("Local fixture verification requires the authenticated admin")
    app = Application(user.uid, organization_admin=True)
    if args.verify_evaluation_uid:
        for evaluation_uid in args.verify_evaluation_uid:
            evaluation = app.evaluation(evaluation_uid)
            assert not evaluation["stale"]
            snapshot = evaluation["input_snapshot"]
            request, _ = plan(snapshot)
            CompareDocumentsResponse.model_validate(snapshot["comparison_result"]).validate_request(
                request
            )
            assert any(
                any(ref.get("citations") for ref in finding["document_references"])
                for finding in evaluation["findings"]
            )
        print(
            json.dumps(
                {
                    "result": "retained_comparisons_verified",
                    "source_uid": uid,
                    "evaluations": [str(v) for v in args.verify_evaluation_uid],
                }
            )
        )
        return
    # Source identity was verified above before any catalog or business writes.
    publish_catalog(app.db)
    from src.backoffice.processing.workflow import BucketUpload, Worker, upload_and_start
    from src.backoffice.services.contracts import (
        AssignmentDocuments,
        AssignSet,
        CreatePerson,
        Evaluate,
        ReviewDocument,
    )
    from tests.api.test_document_comparisons import ComparisonParser
    from tests.api.test_document_processing import Bucket, Dispatcher, Parser, png

    bucket, dispatcher = Bucket(), Dispatcher()
    app.bucket = bucket
    person = app.create_person(
        CreatePerson(
            operation_key=uuid4(),
            profile={
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
        )
    )
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/documents"
    documents = {}
    for kind in ("passport", "national_identity_card", "loan_contract", "employer_confirmation"):
        payload = json.loads((root / f"{kind}.json").read_text())
        content = png()
        command = BucketUpload(
            operation_key=uuid4(),
            person_uid=person["uid"],
            filename="synthetic.png",
            media_type="image/png",
            byte_count=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        run = upload_and_start(app, command, content, bucket=bucket, dispatcher=dispatcher)
        result = Worker(app, parser=Parser(payload, kind=kind), bucket=bucket).run(run["uid"])
        assert result["status"] == "completed", result
        doc = result["document"]
        existing_review = app.document(doc["uid"])["latest_review"]
        if existing_review is None:
            app.review(
                doc["uid"],
                ReviewDocument(
                    operation_key=uuid4(),
                    expected_revision=1,
                    expected_decision_sequence=0,
                    decision="accepted",
                    reason="Synthetic source verified",
                ),
            )
        documents[kind] = doc["uid"]
    outcomes = []
    for key, version, kinds in (
        ("loan_requirements", 2, ["loan_contract", "employer_confirmation"]),
        ("new_account_requirements", 3, ["passport", "national_identity_card"]),
    ):
        assigned = app.assign(
            person["uid"],
            AssignSet(operation_key=uuid4(), document_set_key=key, document_set_version=version),
        )
        app.set_documents(
            assigned["uid"],
            AssignmentDocuments(
                operation_key=uuid4(),
                expected_revision=1,
                document_uids=[documents[k] for k in kinds],
            ),
        )
        command = Evaluate(operation_key=uuid4(), expected_revision=2)
        launched = app.evaluate(assigned["uid"], command, dispatcher=dispatcher)
        parser = ComparisonParser()
        completed = Worker(app, parser=parser, bucket=bucket).run(launched["processing_run_uid"])
        assert completed["status"] == "completed", completed
        repeated = app.evaluate(assigned["uid"], command, dispatcher=dispatcher)
        assert repeated["uid"] == completed["evaluation"]["uid"] and len(parser.calls) == 1
        evaluation = app.evaluation(repeated["uid"])
        assert not evaluation["stale"]
        outcomes.append({"policy": key, "version": version, "evaluation_uid": repeated["uid"]})
    print(
        json.dumps(
            {"result": "passed", "source_uid": uid, "providers": "controlled", "outcomes": outcomes}
        )
    )


if __name__ == "__main__":
    main()
