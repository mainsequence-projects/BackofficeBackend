"""Comparison stage on the existing durable processing worker and evaluation engine."""

from uuid import UUID

from ..services.application import RUN, canonical, fail, stable
from ..services.comparisons import plan
from ..services.contracts import Command, Evaluate, EvaluateCase
from .comparison_contracts import CompareDocumentsResponse

KIND = "document.compare"


class StartComparison(Command):
    assignment_uid: UUID
    expected_revision: int
    evaluation_operation_key: UUID


def start(app, uid, command, dispatcher=None):
    from .workflow import dispatch, get_run

    assignment = app.assignment(uid, reading=False)

    def build(op, now):
        snapshot = app.evaluation_input(uid)
        if snapshot["assignment"]["revision"] != command.expected_revision:
            fail(409, "stale_assignment_revision")
        # Validate selection and bounds before scheduling; missing evidence becomes findings.
        plan(snapshot)
        run_uid = stable(command.operation_key, "comparison")
        row = dict(
            uid=run_uid,
            operation_key=run_uid,
            kind=KIND,
            status="pending",
            attempt_count=0,
            job_run_uid=None,
            agent_session_uid=None,
            inference_request_uid=None,
            created_at=now,
            updated_at=now,
            lease_token=None,
            lease_expires_at=None,
            input_snapshot={
                "actor_uid": app.actor,
                "person_uid": assignment["person_uid"],
                "assignment_uid": str(uid),
                "evaluation_command": command.model_dump(mode="json"),
                "evaluation_input": snapshot,
            },
            result={"stage": "pending"},
        )
        return [app.ensure_step(RUN, row)], {"uid": run_uid}

    outcome = app.mutate(
        assignment["person_uid"],
        StartComparison(
            operation_key=stable(command.operation_key, "comparison-request"),
            assignment_uid=uid,
            expected_revision=command.expected_revision,
            evaluation_operation_key=command.operation_key,
        ),
        "assignment.comparison_requested",
        build,
    )
    result = dispatch(app, get_run(app, outcome["uid"]), dispatcher)
    if result["status"] == "completed":
        return result["evaluation"]
    return {**result, "processing_run_uid": outcome["uid"]}


def run(worker, row, result):
    from .workflow import view

    app = worker.app
    inputs = row["input_snapshot"]
    frozen = inputs["evaluation_input"]
    # A completed durable evaluation intent must be recoverable even after later edits.
    # Preserve legacy intents while retaining the case-bound MCP command verbatim.
    command_type = EvaluateCase if "case_uid" in inputs["evaluation_command"] else Evaluate
    command = command_type.model_validate(inputs["evaluation_command"])
    completed_intent = app.db.one(RUN, uid=command.operation_key)
    if completed_intent is None and canonical(
        app.evaluation_input(inputs["assignment_uid"], processing=True)
    ) != canonical(frozen):
        result["error_code"] = "comparison_inputs_changed_start_new_evaluation"
        return view(worker.save(row, result, "needs_input"))
    request, _ = plan(frozen)
    if request is not None and "comparison_response" not in result:
        response = CompareDocumentsResponse.model_validate(worker.parser.compare(request))
        response.validate_request(request)
        result.update(comparison_response=response.model_dump(mode="json"), stage="compared")
        row = worker.save(row, result)
    if request is not None:
        CompareDocumentsResponse.model_validate(result["comparison_response"]).validate_request(
            request
        )
    if "evaluation" not in result:
        worker.assert_claim(row["uid"])
        from fastapi import HTTPException

        try:
            result["evaluation"] = app.evaluate(
                inputs["assignment_uid"],
                command,
                processing=True,
                comparison_run=row["uid"],
            )
        except HTTPException as exc:
            if exc.detail == "comparison_inputs_changed_start_new_evaluation":
                result["error_code"] = exc.detail
                return view(worker.save(row, result, "needs_input"))
            raise
    result["stage"] = "completed"
    return view(worker.save(row, result, "completed"))
