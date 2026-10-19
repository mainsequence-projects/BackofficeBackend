"""Main Sequence migration Job; never invoked by application startup."""

from metatables import upgrade_application

PROVIDER = "src.backoffice.migrations:migration"


def main() -> None:
    result = upgrade_application(PROVIDER)
    from src.backoffice.services.application import publish_catalog

    publish_catalog()
    state = "migrated" if result["migrated"] else "already current"
    print(f"{PROVIDER}: {result['revision']} ({state}) on {result['data_source_uid']}", flush=True)


if __name__ == "__main__":
    main()
