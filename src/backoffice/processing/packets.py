"""Conservative document grouping over immutable, subject-owned source pages."""

from ..services.application import RUN, stable
from ..services.contracts import Command
from ..services.parsing_confidence import document_classification
from .adapters import ProcessingError


def document_groups(pages):
    """Use explicit boundaries or an isolated type between two complete boundaries.

    No file-name hints, expected dataset labels or inferred missing pages. An
    ambiguous packet remains needs_input without creating partial documents.
    """
    from .workflow import requires_document_grouping

    groups, inferred = [], set()
    ordered = sorted(pages, key=lambda p: p.page)
    for index, page in enumerate(ordered):
        if page.document_type is None:
            return None
        previous = groups[-1][-1] if groups else None
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        isolated_type = (
            page.boundary == "unknown"
            and previous is not None
            and following is not None
            and previous.document_type != page.document_type
            and following.document_type != page.document_type
            and previous.printed_page_count is not None
            and previous.printed_page_number == previous.printed_page_count
            and following.boundary == "starts_document"
            and page.printed_page_number in (None, 1)
            and page.printed_page_count in (None, 1)
        )
        if page.boundary == "starts_document" or isolated_type:
            groups.append([page])
            if isolated_type:
                inferred.add(page.page)
        elif (
            groups
            and page.boundary == "continues_document"
            and page.document_type == groups[-1][0].document_type
        ):
            groups[-1].append(page)
        else:
            return None
    if len(groups) < 2:
        return None
    result = []
    for group in groups:
        numbers = [p.page for p in group]
        if numbers != list(range(numbers[0], numbers[-1] + 1)):
            return None
        if requires_document_grouping(group):
            return None
        if any(
            (p.printed_page_count is not None and p.printed_page_count != len(group))
            or (p.printed_page_number is not None and p.printed_page_number != i + 1)
            for i, p in enumerate(group)
        ):
            return None
        result.append(
            {
                "document_type": group[0].document_type,
                "pages": numbers,
                **(
                    {"boundary_basis": "isolated_type_between_complete_boundaries"}
                    if numbers[0] in inferred
                    else {}
                ),
            }
        )
    return result


def run_packet(worker, row, result):
    """One idempotent normal extraction run per group; retain original page numbers."""
    from .workflow import KIND, Worker, view

    app = worker.app
    for group in result["groups"]:
        worker.assert_claim(row["uid"])
        selection = group["pages"]
        operation = stable(row["uid"], "pages:" + ",".join(map(str, selection)))
        uid = stable(operation, "extraction")

        def build(op, now, selection=selection, row=row, uid=uid):
            classified = {
                **result["classification"],
                "pages": [p for p in result["classification"]["pages"] if p["page"] in selection],
            }
            summary = document_classification(
                classified["pages"],
                expected_pages={(p["source_file"], p["page"]) for p in classified["pages"]},
            ).model_dump(mode="json")
            child = {
                **{k: row[k] for k in ("agent_session_uid", "inference_request_uid")},
                "uid": uid,
                "operation_key": uid,
                "kind": KIND,
                "status": "pending",
                "attempt_count": 0,
                "job_run_uid": None,
                "created_at": now,
                "updated_at": now,
                "lease_token": None,
                "lease_expires_at": None,
                "input_snapshot": {
                    **row["input_snapshot"],
                    "parent_packet_uid": row["uid"],
                    "page_selection": selection,
                    "allow_document_groups": False,
                },
                "result": {
                    "stage": "classified",
                    "source_object": result["source_object"],
                    "classification": classified,
                    "classification_summary": summary,
                },
            }
            return [app.ensure_step(RUN, child)], {"uid": uid}

        app.mutate(
            row["input_snapshot"]["person_uid"],
            Command(operation_key=operation),
            "document.packet_group_created",
            build,
            processing=True,
        )
        child = Worker(app, parser=worker.parser, bucket=worker.bucket, clock=worker.clock).run(uid)
        group["run_uid"] = uid
        group["status"] = child["status"]
        group["error_code"] = child.get("error_code")
        if child.get("document"):
            group["document"] = child["document"]
            group["completion"] = child.get("completion")
        result["documents"] = [g["document"] for g in result["groups"] if g.get("document")]
        row = worker.save(row, result)
        if child["status"] != "completed":
            # Retry the same parent resumes the same child and its checkpoints.
            raise ProcessingError(child.get("error_code") or "packet_group_incomplete")
    result["stage"] = "completed"
    return view(worker.save(row, result, "completed"))
