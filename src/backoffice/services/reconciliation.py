"""Deterministic coverage checks over frozen evidence, never a document-authenticity claim."""

import unicodedata
from datetime import date

from ..models.document_set import DocumentSet


def field(value, path):
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def assess(document, option, person, today):
    if document["status"] != "submitted":
        return "needs_information", "DRAFT_NOT_SUBMITTED", ["payload"]
    if document["review_status"] == "rejected":
        return "failed", "DOCUMENT_REJECTED", []
    if not document["accepted"]:
        return "pending_review", "REVIEW_REQUIRED", []
    payload = document["payload"]
    missing = [
        path for path in option.required_fields if field(payload, path) in (None, "", [], {})
    ]
    if missing:
        return "needs_information", "REQUIRED_FIELD_MISSING", missing
    if option.require_unexpired:
        expiration = payload.get("expiration_date")
        if payload.get("validity_type") == "permanent":
            pass
        elif not expiration:
            return "needs_information", "VALIDITY_UNKNOWN", ["expiration_date"]
        elif date.fromisoformat(expiration) < today:
            return "failed", "DOCUMENT_EXPIRED", ["expiration_date"]
        if payload.get("issue_date") and date.fromisoformat(payload["issue_date"]) > today:
            return "failed", "DOCUMENT_NOT_YET_VALID", ["issue_date"]
    if option.max_age_days is not None:
        value = field(payload, option.freshness_field)
        if not value:
            return "needs_information", "FRESHNESS_DATE_MISSING", [option.freshness_field]
        age = (today - date.fromisoformat(value)).days
        if age < 0 or age > option.max_age_days:
            return "failed", "DOCUMENT_OUTSIDE_FRESHNESS_WINDOW", [option.freshness_field]
    names = []
    for key in ("full_name", "employee_name", "taxpayer_name", "owner_name", "account_holder_name"):
        if payload.get(key):
            names.append(payload[key])
    names += payload.get("account_holders") or []
    if names:
        reference = person.get("full_name")
        if not reference:
            return "needs_information", "REFERENCE_NAME_MISSING", ["person.full_name"]
        if normalized(reference) not in [normalized(name) for name in names]:
            return "failed", "NAME_MISMATCH", ["person.full_name"]
    if payload.get("date_of_birth"):
        if not person.get("date_of_birth"):
            return "needs_information", "REFERENCE_BIRTH_DATE_MISSING", ["person.date_of_birth"]
        if payload["date_of_birth"] != person["date_of_birth"]:
            return "failed", "BIRTH_DATE_MISMATCH", ["date_of_birth"]
    address = payload.get("service_address") or payload.get("holder_address")
    if address and option.document_type in ("utility_bill", "bank_statement"):
        reference = person.get("residential_address")
        if not reference:
            return "needs_information", "REFERENCE_ADDRESS_MISSING", ["person.residential_address"]
        for key, expected in reference.items():
            if expected:
                if not address.get(key):
                    return "needs_information", "DOCUMENT_ADDRESS_INCOMPLETE", [f"address.{key}"]
                if normalized(address[key]) != normalized(expected):
                    return "failed", "ADDRESS_MISMATCH", [f"address.{key}"]
    if (
        payload.get("employment_status")
        and person.get("employment_status")
        and normalized(payload["employment_status"]) != normalized(person["employment_status"])
    ):
        return "failed", "EMPLOYMENT_STATUS_MISMATCH", ["employment_status"]
    return "satisfied", "QUALIFYING_DOCUMENT", []


def reconcile(snapshot):
    policy = DocumentSet.model_validate(snapshot["policy"])
    person, today = snapshot["person"], date.fromisoformat(snapshot["evaluation_date"])
    findings, used = [], set()
    mandatory_total = satisfied_total = 0
    for requirement in policy.requirements:
        status, code, paths, refs = "missing", "EVIDENCE_MISSING", [], []
        condition = requirement.condition
        applies = True
        if condition:
            value = person.get(condition.field)
            if value is None:
                applies = None
            else:
                applies = value == condition.equals
        if applies is False:
            status, code = "not_applicable", "CONDITION_NOT_APPLICABLE"
        elif applies is None:
            status, code, paths = (
                "needs_information",
                "APPLICABILITY_UNKNOWN",
                [f"person.{condition.field}"],
            )
        else:
            eligible, failures, seen_hashes, seen_periods = [], [], set(), set()
            for document in snapshot["documents"]:
                option = next(
                    (
                        o
                        for o in requirement.options
                        if o.document_type == document["document_type"]
                        and o.schema_version == document["schema_version"]
                    ),
                    None,
                )
                if option is None or (not policy.allow_document_reuse and document["uid"] in used):
                    continue
                result = assess(document, option, person, today)
                ref = {
                    "document_uid": document["uid"],
                    "revision": document["revision"],
                    "review_uid": (document["latest_review"] or {}).get("uid"),
                }
                if result[0] != "satisfied":
                    failures.append((*result, ref))
                    continue
                hashes = set(document["source_hashes"])
                period = (
                    field(document["payload"], requirement.distinct_period_field)
                    if requirement.distinct_period_field
                    else None
                )
                period_key = (
                    (period.get("start_date"), period.get("end_date"))
                    if isinstance(period, dict)
                    else None
                )
                if hashes & seen_hashes or (period_key is not None and period_key in seen_periods):
                    failures.append(("failed", "DUPLICATE_EVIDENCE_OR_PERIOD", [], ref))
                    continue
                if requirement.distinct_period_field and period_key is None:
                    failures.append(
                        (
                            "needs_information",
                            "REPORTING_PERIOD_MISSING",
                            [requirement.distinct_period_field],
                            ref,
                        )
                    )
                    continue
                seen_hashes |= hashes
                if period_key:
                    seen_periods.add(period_key)
                eligible.append(ref)
            refs = eligible
            if len(eligible) >= requirement.min_count:
                status, code = "satisfied", "REQUIREMENT_SATISFIED"
                used.update(ref["document_uid"] for ref in eligible[: requirement.min_count])
            elif failures:
                priority = {"failed": 0, "needs_information": 1, "pending_review": 2}
                status, code, paths, failed_ref = min(failures, key=lambda x: priority[x[0]])
                refs = [*eligible, failed_ref]
            elif eligible:
                code = "INSUFFICIENT_DISTINCT_DOCUMENTS"
        if requirement.mandatory and applies is not False:
            mandatory_total += 1
            satisfied_total += status == "satisfied"
        explanation = f"{requirement.description} {code.replace('_', ' ').capitalize()}."
        findings.append(
            {
                "requirement_key": requirement.key,
                "status": status,
                "reason_code": code,
                "explanation": explanation,
                "field_paths": paths,
                "document_references": refs,
            }
        )
    return findings, {
        "complete": mandatory_total == satisfied_total,
        "mandatory_requirements": mandatory_total,
        "satisfied_requirements": satisfied_total,
        "evaluation_date": today.isoformat(),
        "policy_notice": policy.description,
    }
