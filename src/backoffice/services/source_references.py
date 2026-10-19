"""Bind parser source references from known attachments, never from guessed text."""


def bind_portrait_source(payload, refs):
    portrait = payload.get("portrait_reference")
    sources = {str(ref["raw_document_uid"]) for ref in refs}
    if (
        isinstance(portrait, dict)
        and portrait.get("raw_document_uid") is None
        and portrait.get("page_number") is not None
        and len(sources) == 1
    ):
        return {
            **payload,
            "portrait_reference": {
                **portrait,
                "raw_document_uid": next(iter(sources)),
            },
        }
    return payload
