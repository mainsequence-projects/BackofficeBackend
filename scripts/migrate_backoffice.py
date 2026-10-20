"""Main Sequence migration Job; never invoked by application startup."""

from metatables import upgrade_application

PROVIDER = "src.backoffice.migrations:migration"


def main() -> None:
    print("Applying and finalizing Back Office table migrations.", flush=True)
    result = upgrade_application(PROVIDER)
    from src.backoffice.services.application import publish_catalog

    print("Publishing Back Office forms and policies; migration Job is still running.", flush=True)
    publish_catalog()
    state = "migrated" if result["migrated"] else "already current"
    print(f"{PROVIDER}: {result['revision']} ({state}) on {result['data_source_uid']}", flush=True)


if __name__ == "__main__":
    main()
