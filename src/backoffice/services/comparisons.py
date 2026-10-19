"""Evidence selection and deterministic comparison rules for every document set."""

import hashlib
from decimal import Decimal, DecimalException, localcontext

from ..models.document_set import DocumentSet
from ..processing.comparison_contracts import (
    CompareDocumentsRequest,
    CompareDocumentsResponse,
    ComparisonCitation,
    ComparisonDocument,
    ComparisonFact,
    ComparisonQuestion,
    FactReference,
    canonical_json,
)
from ..processing.evidence_contracts import ExtractionResponseV2, pointer_value
from .application import canonical, fail


def pointer(path):
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in path.split("."))


def fact(document, path):
    """Only selected, revision-bound and source-bound facts may enter a comparison."""
    snapshot = document.get("extraction_evidence")
    if not snapshot:
        raise ValueError("missing cited extraction")
    if (
        snapshot["content_sha256"]
        != hashlib.sha256(
            canonical({k: v for k, v in snapshot.items() if k != "content_sha256"}).encode()
        ).hexdigest()
    ):
        raise ValueError("evidence checksum mismatch")
    extraction = ExtractionResponseV2.model_validate(snapshot["extraction"])
    ptr = pointer(path)
    value = pointer_value(document["payload"], ptr)
    field = next((f for f in extraction.field_evidence if f.pointer == ptr), None)
    selected = (
        next((c for c in field.candidates if c.reader_id == field.selected_reader_id), None)
        if field
        else None
    )
    if selected is None or value is None or canonical(value) != canonical(selected.value):
        raise ValueError("missing or changed selected fact")
    pages = {(p.source_file, p.page): p for p in extraction.pages}
    sources = {r["raw_document_uid"] for r in document["raw_document_refs"]}
    citations = []
    for location in selected.locations:
        page = pages[(location.source_file, location.page)]
        source_id = snapshot["source_mapping"][page.source_file]
        if source_id not in sources or page.source_sha256 not in document["source_hashes"]:
            raise ValueError("comparison citation has different source identity")
        citations.append(
            ComparisonCitation(
                source_id=source_id,
                source_sha256=page.source_sha256,
                page=page.page,
                page_sha256=page.page_sha256,
                bounding_box=location.bounding_box,
                rotation_degrees=page.rotation_degrees,
            )
        )
    return ComparisonFact(pointer=ptr, value=value, citations=citations)


def plan(snapshot):
    policy = DocumentSet.model_validate(snapshot["policy"])
    documents, questions, bindings = {}, [], []
    for rule in policy.comparisons:
        sides = [
            [
                d
                for d in snapshot["documents"]
                if (d["document_type"], d["schema_version"]) == (s.document_type, s.schema_version)
            ]
            for s in (rule.left, rule.right)
        ]
        binding = {"key": rule.key, "pairs": [], "blockers": [], "references": []}
        if not all(sides):
            binding["blockers"].append(
                ("not_applicable", "COMPARISON_NOT_APPLICABLE")
                if rule.when_both_present
                else ("missing", "COMPARISON_DOCUMENT_MISSING")
            )
        seen = set()
        for left in sides[0]:
            for right in sides[1]:
                if left["uid"] == right["uid"]:
                    continue
                pair_id = (left["uid"], right["uid"])
                if rule.left == rule.right:
                    pair_id = tuple(sorted(pair_id))
                if pair_id in seen:
                    continue
                seen.add(pair_id)
                refs = [
                    {
                        "document_uid": d["uid"],
                        "revision": d["revision"],
                        "review_uid": (d["latest_review"] or {}).get("uid"),
                    }
                    for d in (left, right)
                ]
                binding["references"].extend(refs)
                if any(d["status"] != "submitted" or not d["accepted"] for d in (left, right)):
                    binding["blockers"].append(
                        ("pending_review", "COMPARISON_DOCUMENT_REVIEW_REQUIRED")
                    )
                    continue
                collected = []
                try:
                    for document, selector in ((left, rule.left), (right, rule.right)):
                        paths = list(
                            dict.fromkeys(
                                [
                                    selector.field,
                                    *selector.context_fields,
                                    *([selector.unit_field] if selector.unit_field else []),
                                ]
                            )
                        )
                        collected.append({path: fact(document, path) for path in paths})
                except (ValueError, KeyError, TypeError):
                    binding["blockers"].append(
                        ("needs_information", "COMPARISON_CITED_FACT_REQUIRED")
                    )
                    continue
                if rule.left.unit_field and canonical(
                    collected[0][rule.left.unit_field].value
                ) != canonical(collected[1][rule.right.unit_field].value):
                    binding["blockers"].append(("needs_information", "COMPARISON_UNIT_MISMATCH"))
                    continue
                key = hashlib.sha256(canonical([rule.key, *pair_id]).encode()).hexdigest()
                context = []
                for document, selector, facts in (
                    (left, rule.left, collected[0]),
                    (right, rule.right, collected[1]),
                ):
                    if document["uid"] not in documents:
                        extraction = document["extraction_evidence"]["extraction"]
                        documents[document["uid"]] = {
                            "document_id": document["uid"],
                            "revision": document["revision"],
                            "document_type": document["document_type"],
                            "schema_version": document["schema_version"],
                            "schema_hash": extraction["schema_hash"],
                            "evidence_sha256": document["extraction_evidence"]["content_sha256"],
                            "facts": {},
                        }
                    for path, observed in facts.items():
                        documents[document["uid"]]["facts"][observed.pointer] = observed
                        if path != selector.field:
                            context.append(
                                FactReference(document_id=document["uid"], pointer=observed.pointer)
                            )
                questions.append(
                    ComparisonQuestion(
                        key=key,
                        topic=rule.topic,
                        left=FactReference(
                            document_id=left["uid"], pointer=pointer(rule.left.field)
                        ),
                        right=FactReference(
                            document_id=right["uid"], pointer=pointer(rule.right.field)
                        ),
                        context=context,
                    )
                )
                binding["pairs"].append(key)
                if len(questions) > 50 or len(documents) > 20:
                    fail(422, "comparison_input_limit_exceeded")
        if all(sides) and not seen:
            binding["blockers"].append(("missing", "COMPARISON_DISTINCT_DOCUMENT_REQUIRED"))
        bindings.append(binding)
    request = (
        CompareDocumentsRequest(
            contract_version=1,
            documents=[
                ComparisonDocument(**{**d, "facts": list(d["facts"].values())})
                for d in documents.values()
            ],
            comparisons=questions,
        )
        if questions
        else None
    )
    return request, bindings


def decide(rule, observation):
    if observation.comparability != "comparable":
        return "pending_review", "COMPARISON_BASIS_UNRESOLVED"
    if rule.operator == "semantic":
        if observation.relationship == "uncertain":
            return "pending_review", "COMPARISON_MEANING_UNRESOLVED"
        equal = observation.relationship == "equivalent"
    elif rule.operator == "exact":
        equal = canonical_json(observation.left.value) == canonical_json(observation.right.value)
    else:
        # Decimal arithmetic, with neither currency conversion nor LLM arithmetic.
        try:
            values = [o.value for o in (observation.left, observation.right)]
            if any(isinstance(v, bool) or not isinstance(v, (str, int, float)) for v in values):
                raise ValueError("not numeric")
            if any(len(str(v)) > 128 for v in values):
                raise ValueError("numeric value outside supported precision")
            left, right = [Decimal(str(v)) for v in values]
            if not left.is_finite() or not right.is_finite():
                raise ValueError("non-finite number")
            if any(
                abs(v.adjusted()) > 100 or abs(v.as_tuple().exponent) > 100 for v in (left, right)
            ):
                raise ValueError("numeric value outside supported range")
            with localcontext() as context:
                context.prec = 256
                allowed = max(
                    rule.absolute_tolerance,
                    abs(left) * Decimal(rule.relative_tolerance_basis_points) / Decimal(10000),
                )
                equal = abs(left - right) <= allowed
        except (ValueError, DecimalException):
            return "needs_information", "COMPARISON_NUMERIC_VALUE_REQUIRED"
    return (
        ("satisfied", "COMPARISON_RULE_SATISFIED")
        if equal
        else ("failed", "COMPARISON_RULE_FAILED")
    )


def findings(snapshot, result=None, *, diagnostics=False):
    policy = DocumentSet.model_validate(snapshot["policy"])
    request, bindings = plan(snapshot)
    observed = {}
    if result is not None and request is not None:
        response = CompareDocumentsResponse.model_validate(result).validate_request(request)
        observed = {o.key: o for o in response.observations}
    output = []
    priority = {
        "failed": 0,
        "missing": 1,
        "needs_information": 2,
        "pending_review": 3,
        "satisfied": 4,
        "not_applicable": 5,
    }
    for rule, binding in zip(policy.comparisons, bindings, strict=True):
        outcomes = list(binding["blockers"])
        refs = list(binding["references"])
        for key in binding["pairs"]:
            observation = observed.get(key)
            outcomes.append(
                decide(rule, observation)
                if observation
                else ("pending_review", "COMPARISON_OBSERVATIONS_REQUIRED")
            )
            if observation:
                for side in (observation.left, observation.right):
                    refs.append(
                        {
                            "document_uid": side.document_id,
                            "revision": side.revision,
                            "comparison_key": key,
                            "pointer": side.pointer,
                            "value": side.value,
                            "citations": [c.model_dump() for c in side.citations],
                        }
                    )
        status, code = min(
            outcomes or [("needs_information", "COMPARISON_EVIDENCE_REQUIRED")],
            key=lambda x: priority[x[0]],
        )
        item = {
            "requirement_key": rule.key,
            "status": status,
            "reason_code": code,
            "explanation": f"{rule.description} {code.replace('_', ' ').capitalize()}.",
            "field_paths": [rule.left.field, rule.right.field],
            "document_references": refs,
        }
        if diagnostics:
            item.update(
                mandatory=rule.mandatory,
                applicable=status != "not_applicable",
                alternatives=[],
                required_count=len(binding["pairs"]) or 1,
                qualifying_count=sum(s == "satisfied" for s, _ in outcomes),
                shortfall=sum(s not in {"satisfied", "not_applicable"} for s, _ in outcomes),
                next_action="Review the cited comparison evidence."
                if status not in {"satisfied", "not_applicable"}
                else "No comparison action required.",
            )
        output.append(item)
    return output
