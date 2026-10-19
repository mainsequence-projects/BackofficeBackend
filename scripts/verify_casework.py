"""Verify case responsibility through an explicitly selected local MetaTables API."""

import argparse
import json
from uuid import UUID, uuid4


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source-uid", required=True, type=UUID)
    cli.add_argument("--verify-case-uid", type=UUID)
    args = cli.parse_args()
    from metatables import configure_local_client, get_runtime_status

    from scripts.developer_session import configure_developer_session
    from scripts.local_api import require_local_runtime

    configure_developer_session()
    configure_local_client()
    source = require_local_runtime(get_runtime_status())
    if source != str(args.source_uid):
        raise RuntimeError("Refusing unexpected local source")
    from mainsequence.client import User

    from src.backoffice.services.application import Application, publish_catalog
    from src.backoffice.services.casework import queue, reviewers, set_my_membership, workspace
    from src.backoffice.services.contracts import AssignSet, CreatePerson, SetMyCaseMembership

    user = User.get_authenticated_user_details()
    if user.is_organization_admin is not True:
        raise RuntimeError("Local fixture verification requires the authenticated admin")
    app = Application(user.uid, organization_admin=True, actor_display_name="Local test reviewer")
    if args.verify_case_uid:
        case = workspace(app, args.verify_case_uid)
        assert case["subject"]["full_name"].startswith("Synthetic reviewer verification")
        assert len(case["reviewers"]["items"]) == 2
        assert case["subject"]["uid"] not in {r["reviewer_uid"] for r in case["reviewers"]["items"]}
        print(
            json.dumps(
                {
                    "result": "persisted_memberships_verified",
                    "case_uid": str(args.verify_case_uid),
                    "source_uid": source,
                }
            )
        )
        return
    # Runtime identity is checked above before any business or catalog writes.
    publish_catalog(app.db)
    subject = app.create_person(
        CreatePerson(
            operation_key=uuid4(),
            profile={
                "full_name": f"Synthetic reviewer verification {str(uuid4())[:8]}",
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
    cases = []
    for key, version in (("loan_requirements", 2), ("new_account_requirements", 3)):
        assigned = app.assign(
            subject["uid"],
            AssignSet(operation_key=uuid4(), document_set_key=key, document_set_version=version),
        )
        case_uid = assigned["uid"]
        snapshot = app.evaluation_input(case_uid)
        command = SetMyCaseMembership(operation_key=uuid4(), expected_revision=0, assigned=True)
        set_my_membership(app, case_uid, command)
        set_my_membership(app, case_uid, command)  # Retry same operation safely.
        # Synthetic second actor exercises the service over local storage only.
        other = Application(uuid4(), reviewer=True, actor_display_name="Synthetic second reviewer")
        set_my_membership(
            other,
            case_uid,
            SetMyCaseMembership(operation_key=uuid4(), expected_revision=0, assigned=True),
        )
        assert len(reviewers(app, case_uid)["items"]) == 2
        assert app.evaluation_input(case_uid) == snapshot
        view = workspace(app, case_uid)
        assert view["subject"]["uid"] == subject["uid"]
        assert view["workflow_state"] == "missing_evidence"
        mine = queue(app, search=view["subject"]["full_name"], responsibility="mine", set_key=key, limit=1)
        assert mine["total_items"] == 1 and mine["items"][0]["uid"] == case_uid
        assert not queue(app, search=view["subject"]["full_name"], responsibility="unassigned")["items"]
        cases.append(case_uid)
    print(json.dumps({"result": "casework_verified", "source_uid": source, "cases": cases}))


if __name__ == "__main__":
    main()
