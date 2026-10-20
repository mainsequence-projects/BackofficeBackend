"""Product V1 reconciles document facts; portraits and face comparison are V2."""


def document_facts(payload: dict) -> dict:
    """Omit obsolete portrait metadata from new revisions, retaining raw sources."""
    return {key: value for key, value in payload.items() if key != "portrait_reference"}
