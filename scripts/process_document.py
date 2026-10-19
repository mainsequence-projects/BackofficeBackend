"""Trusted Main Sequence Job; accepts only a persisted extraction or comparison run UID."""

import argparse
import json
import os
from uuid import UUID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-uid", required=True, type=UUID)
    parser.add_argument(
        "--local", action="store_true", help="Use the verified local SQLite runtime."
    )
    args = parser.parse_args()
    if args.local:
        from metatables import configure_local_client, get_runtime_status

        from scripts.developer_session import configure_developer_session
        from scripts.local_api import require_local_runtime

        configure_developer_session()
        configure_local_client()
        require_local_runtime(get_runtime_status())
    from mainsequence.client import User

    from src.backoffice.processing.workflow import Worker
    from src.backoffice.services.application import Application

    user = User.get_authenticated_user_details()
    allowed = {
        x.strip()
        for x in os.environ.get("BACKOFFICE_PARSING_PROCESSOR_UIDS", "").split(",")
        if x.strip()
    }
    app = Application(
        user.uid,
        organization_admin=user.is_organization_admin is True,
        parsing_processor=user.uid in allowed,
    )
    result = Worker(app).run(args.run_uid)
    # Only business references and bounded error codes are emitted, never extracted attributes.
    print(json.dumps(result), flush=True)
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
