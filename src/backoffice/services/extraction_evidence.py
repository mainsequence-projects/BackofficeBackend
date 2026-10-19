"""Revision-bound extraction evidence in the common document mutation/review engine."""

import hashlib

from ..processing.evidence_contracts import ClassificationResponseV2, ExtractionResponseV2
from ..tables.evidence import FieldEvidenceRecord
from .application import DR, RAW, RUN, canonical, fail, stable


def evidence_steps(app, evidence, person_uid, command, op, now, refs):
    if evidence is None:
        return None, []
    classification = ClassificationResponseV2.model_validate(evidence["classification"])
    extraction = ExtractionResponseV2.model_validate(evidence["extraction"])
    run = app.required(RUN, uid=evidence["run_uid"])
    source_uid = run["input_snapshot"]["source_uid"]
    source = app.required(RAW, uid=source_uid)
    if (
        run["kind"] != "document.extract"
        or source["person_uid"] != str(person_uid)
        or run["input_snapshot"]["person_uid"] != str(person_uid)
        or [r["raw_document_uid"] for r in refs] != [source_uid]
        or any(r.get("first_page") or r.get("last_page") for r in refs)
        or extraction.attributes != command.payload
        or extraction.document_type != command.document_type
        or extraction.schema_version != command.schema_version
        or op != stable(run["uid"], "draft")
    ):
        fail(422, "extraction_evidence_identity_mismatch")
    expected_hash = run["input_snapshot"]["schemas"][command.document_type]["content_sha256"]
    if extraction.schema_hash != expected_hash:
        fail(422, "extraction_evidence_schema_mismatch")

    def manifest(pages):
        return {(p.source_file, p.page, p.source_sha256, p.page_sha256) for p in pages}

    if (
        manifest(classification.pages) != manifest(extraction.pages)
        or any(p.source_sha256 != source["content_sha256"] for p in extraction.pages)
        or len({p.source_file for p in extraction.pages}) != 1
    ):
        fail(422, "extraction_evidence_source_mismatch")
    snapshot = {
        "contract_version": 2,
        "run_uid": run["uid"],
        "source_mapping": {extraction.pages[0].source_file: source_uid},
        "classification": classification.model_dump(mode="json"),
        "extraction": extraction.model_dump(mode="json"),
    }
    snapshot["content_sha256"] = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
    steps = []
    for field in extraction.field_evidence:
        for candidate in field.candidates:
            for index, location in enumerate(candidate.locations):
                steps.append(
                    app.ensure_step(
                        FieldEvidenceRecord.__table__,
                        {
                            "uid": stable(
                                op,
                                "field:" + canonical([field.pointer, candidate.reader_id, index]),
                            ),
                            "created_at": now,
                            "revision_uid": stable(op, "revision"),
                            "person_uid": str(person_uid),
                            "field_path": field.pointer,
                            "raw_document_uid": source_uid,
                            "page_number": location.page,
                            "bounding_box": location.bounding_box,
                            "excerpt": candidate.raw_text,
                            "provenance": {
                                "run_uid": run["uid"],
                                "reader_id": candidate.reader_id,
                                "model": candidate.model,
                                "value": candidate.value,
                                "confidence": candidate.confidence,
                                "agreement": field.agreement,
                                "selected_reader_id": field.selected_reader_id,
                                "normalization_version": extraction.normalization_version,
                                "evidence_sha256": snapshot["content_sha256"],
                            },
                        },
                    )
                )
    return snapshot, steps


def evidence_view(app, uid, revision):
    # Use the same case authorization and unfinished-mutation guard as document reads.
    app.document(uid, revision_number=revision)
    row = app.required(DR, document_uid=uid, revision=revision)
    return {
        "document_uid": str(uid),
        "revision": revision,
        "evidence": row.get("extraction_evidence"),
    }


def review_reason(snapshot):
    """Back Office alone decides whether observations prevent automatic acceptance."""
    if snapshot is None:
        return None  # Explicit legacy behavior; no fabricated evidence for old revisions.
    extraction = ExtractionResponseV2.model_validate(snapshot["extraction"])
    if not extraction.evidence_complete:
        return "extraction_evidence_incomplete"
    if any(f.agreement == "disagree" for f in extraction.field_evidence):
        return "extraction_readers_disagree"
    if any(
        len(f.candidates) > 1 and f.agreement == "single_reader" for f in extraction.field_evidence
    ):
        return "extraction_reader_missing"
    return None
