"""Explain revision-bound acceptance blockers without reading mutable current settings."""

from pydantic import ValidationError

from ..schemas.registry import get_document_model


def empty(value):
    return (
        value is None or isinstance(value, str) and not value.strip() or value == [] or value == {}
    )


def attribute_issues(document):
    """Accepted revisions passed submission validation; inspect unaccepted evidence."""
    if document.get("accepted"):
        return None
    try:
        get_document_model(document["document_type"], document["schema_version"]).model_validate(
            document["payload"]
        )
    except ValidationError as error:
        errors = error.errors()
        missing = [e for e in errors if e["type"] == "missing" or empty(e.get("input"))]
        paths = list(dict.fromkeys(".".join(map(str, e["loc"])) for e in missing or errors))
        return (
            "needs_information",
            "REQUIRED_FIELD_MISSING" if missing else "DOCUMENT_ATTRIBUTES_INVALID",
            paths,
        )
    return None


def review_reason(document):
    result = document.get("parsing_result") or {}
    reason = result.get("reason_code")
    score, threshold = (
        result.get("parsing_score_percent"),
        result.get("acceptance_threshold_percent"),
    )
    messages = {
        "parsing_score_below_threshold": (
            f"Classification confidence is {score}%, below the recorded {threshold}% acceptance threshold."
            if score is not None and threshold is not None
            else "Classification confidence was below the recorded acceptance threshold."
        ),
        "parsing_score_missing": "The extractor did not supply a classification confidence score.",
        "automatic_acceptance_disabled": "Automatic acceptance was disabled when this revision was processed.",
        "parsing_policy_missing": "No automatic acceptance policy was recorded when this revision was processed.",
        "extraction_readers_disagree": "The extraction readers disagree about the document's field values.",
        "extraction_reader_missing": "A required extraction reader's result is missing.",
        "extraction_evidence_incomplete": "The extraction does not contain complete source citations for its field values.",
        "invalid_document_attributes": "The extracted document attributes failed validation.",
        "source_evidence_required": "The original source evidence is missing.",
    }
    incomplete = reason in {
        "extraction_reader_missing",
        "extraction_evidence_incomplete",
        "invalid_document_attributes",
        "source_evidence_required",
    }
    return {
        "status": "needs_information" if incomplete else "pending_review",
        "reason_code": reason.upper() if reason in messages else "REVIEW_REQUIRED",
        "explanation": messages.get(
            reason, "This revision was submitted without an automatic acceptance decision."
        ),
        "next_action": "Complete or retry extraction and provide the missing evidence, then run checks again."
        if incomplete
        else "An authorized reviewer must verify this revision and accept or reject it.",
    }


def document_review_requirement(document):
    if document["accepted"] or document["review_status"] == "rejected":
        return None
    issues = attribute_issues(document)
    if issues:
        _, code, paths = issues
        return {
            "status": "needs_information",
            "reason_code": code,
            "field_paths": paths,
            "explanation": "Complete or correct the document fields: "
            + ", ".join(p.replace("_", " ").replace(".", " › ") for p in paths)
            + ".",
            "next_action": "Save the corrected fields and submit the revision before review.",
        }
    if document["status"] != "submitted":
        return {
            "status": "needs_information",
            "reason_code": "DRAFT_NOT_SUBMITTED",
            "explanation": "This draft has not been submitted.",
            "next_action": "Submit the completed revision before review.",
        }
    return review_reason(document)
