"""Create the document reconciliation foundation.

Frozen physical schema: do not import live application models into this revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backoffice__audit_event",
        sa.Column("actor_uid", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_uid", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_uid", sa.Uuid(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__audit_event")),
    )
    op.create_index(
        op.f("ix__backoffice__audit_event__correlation_uid"),
        "backoffice__audit_event",
        ["correlation_uid"],
        unique=False,
    )
    op.create_index(
        op.f("ix__backoffice__audit_event__resource_uid"),
        "backoffice__audit_event",
        ["resource_uid"],
        unique=False,
    )
    op.create_table(
        "backoffice__document_schema",
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("canonical_schema", sa.JSON(), nullable=False),
        sa.Column("draft_schema", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name=op.f("ck__backoffice__document_schema__sha256_length"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck__backoffice__document_schema__positive_version")
        ),
        sa.PrimaryKeyConstraint(
            "document_type", "version", name=op.f("pk__backoffice__document_schema")
        ),
    )
    op.create_table(
        "backoffice__document_set_version",
        sa.Column("set_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status = 'draft' OR published_at IS NOT NULL",
            name=op.f("ck__backoffice__document_set_version__publication_time"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name=op.f("ck__backoffice__document_set_version__allowed_status"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck__backoffice__document_set_version__positive_version")
        ),
        sa.PrimaryKeyConstraint(
            "set_key", "version", name=op.f("pk__backoffice__document_set_version")
        ),
    )
    op.create_table(
        "backoffice__person",
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_revision >= 1", name=op.f("ck__backoffice__person__positive_revision")
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__person")),
    )
    op.create_table(
        "backoffice__processing_run",
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("job_run_uid", sa.Uuid(), nullable=True),
        sa.Column("agent_session_uid", sa.Uuid(), nullable=True),
        sa.Column("inference_request_uid", sa.Uuid(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name=op.f("ck__backoffice__processing_run__allowed_status"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck__backoffice__processing_run__nonnegative_attempts")
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__processing_run")),
        sa.UniqueConstraint(
            "operation_key", name=op.f("uq__backoffice__processing_run__operation_key")
        ),
    )
    op.create_table(
        "backoffice__document",
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_revision IS NULL OR current_revision >= 1",
            name=op.f("ck__backoffice__document__positive_revision"),
        ),
        sa.ForeignKeyConstraint(
            ["person_uid"],
            ["backoffice__person.uid"],
            name=op.f("fk__backoffice__document__person_uid__backoffice__person__uid"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__document")),
        sa.UniqueConstraint(
            "uid",
            "person_uid",
            "document_type",
            name=op.f("uq__backoffice__document__uid__person_uid__document_type"),
        ),
        sa.UniqueConstraint(
            "uid", "person_uid", name=op.f("uq__backoffice__document__uid__person_uid")
        ),
    )
    op.create_index(
        op.f("ix__backoffice__document__person_uid"),
        "backoffice__document",
        ["person_uid"],
        unique=False,
    )
    op.create_table(
        "backoffice__person_document_set",
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("set_key", sa.String(length=120), nullable=False),
        sa.Column("set_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck__backoffice__person_document_set__positive_revision")
        ),
        sa.ForeignKeyConstraint(
            ["person_uid"],
            ["backoffice__person.uid"],
            name=op.f("fk__backoffice__person_document_set__person_uid__bac_db64494250"),
        ),
        sa.ForeignKeyConstraint(
            ["set_key", "set_version"],
            [
                "backoffice__document_set_version.set_key",
                "backoffice__document_set_version.version",
            ],
            name=op.f("fk__backoffice__person_document_set__set_key__set_ve_aa9b335672"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__person_document_set")),
        sa.UniqueConstraint(
            "uid", "person_uid", name=op.f("uq__backoffice__person_document_set__uid__person_uid")
        ),
    )
    op.create_index(
        op.f("ix__backoffice__person_document_set__person_uid"),
        "backoffice__person_document_set",
        ["person_uid"],
        unique=False,
    )
    op.create_table(
        "backoffice__person_revision",
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck__backoffice__person_revision__positive_revision")
        ),
        sa.ForeignKeyConstraint(
            ["person_uid"],
            ["backoffice__person.uid"],
            name=op.f("fk__backoffice__person_revision__person_uid__backoff_389e734301"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__person_revision")),
        sa.UniqueConstraint(
            "person_uid",
            "revision",
            name=op.f("uq__backoffice__person_revision__person_uid__revision"),
        ),
    )
    op.create_table(
        "backoffice__raw_document",
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status != 'ready' OR finalized_at IS NOT NULL",
            name=op.f("ck__backoffice__raw_document__finalization_time"),
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'ready', 'failed')",
            name=op.f("ck__backoffice__raw_document__allowed_status"),
        ),
        sa.CheckConstraint(
            "byte_count > 0", name=op.f("ck__backoffice__raw_document__positive_size")
        ),
        sa.CheckConstraint(
            "chunk_count > 0", name=op.f("ck__backoffice__raw_document__positive_chunks")
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name=op.f("ck__backoffice__raw_document__sha256_length")
        ),
        sa.ForeignKeyConstraint(
            ["person_uid"],
            ["backoffice__person.uid"],
            name=op.f("fk__backoffice__raw_document__person_uid__backoffice_968ea13f87"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__raw_document")),
        sa.UniqueConstraint(
            "operation_key", name=op.f("uq__backoffice__raw_document__operation_key")
        ),
        sa.UniqueConstraint(
            "uid", "person_uid", name=op.f("uq__backoffice__raw_document__uid__person_uid")
        ),
    )
    op.create_index(
        op.f("ix__backoffice__raw_document__person_uid"),
        "backoffice__raw_document",
        ["person_uid"],
        unique=False,
    )
    op.create_table(
        "backoffice__assignment_document",
        sa.Column("assignment_uid", sa.Uuid(), nullable=False),
        sa.Column("document_uid", sa.Uuid(), nullable=False),
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_uid", "person_uid"],
            ["backoffice__person_document_set.uid", "backoffice__person_document_set.person_uid"],
            name=op.f("fk__backoffice__assignment_document__assignment_uid_fe05971b77"),
        ),
        sa.ForeignKeyConstraint(
            ["document_uid", "person_uid"],
            ["backoffice__document.uid", "backoffice__document.person_uid"],
            name=op.f("fk__backoffice__assignment_document__document_uid__p_b87a6d7035"),
        ),
        sa.PrimaryKeyConstraint(
            "assignment_uid", "document_uid", name=op.f("pk__backoffice__assignment_document")
        ),
    )
    op.create_table(
        "backoffice__document_revision",
        sa.Column("document_uid", sa.Uuid(), nullable=False),
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("raw_document_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'draft' AND submitted_at IS NULL) OR (status = 'submitted' AND submitted_at IS NOT NULL)",
            name=op.f("ck__backoffice__document_revision__submission_time"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted')",
            name=op.f("ck__backoffice__document_revision__allowed_status"),
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck__backoffice__document_revision__positive_revision")
        ),
        sa.ForeignKeyConstraint(
            ["document_type", "schema_version"],
            ["backoffice__document_schema.document_type", "backoffice__document_schema.version"],
            name=op.f("fk__backoffice__document_revision__document_type__sc_b3fbcc4fc0"),
        ),
        sa.ForeignKeyConstraint(
            ["document_uid", "person_uid", "document_type"],
            [
                "backoffice__document.uid",
                "backoffice__document.person_uid",
                "backoffice__document.document_type",
            ],
            name=op.f("fk__backoffice__document_revision__document_uid__per_e47b28a47c"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__document_revision")),
        sa.UniqueConstraint(
            "document_uid",
            "revision",
            name=op.f("uq__backoffice__document_revision__document_uid__revision"),
        ),
        sa.UniqueConstraint(
            "uid", "person_uid", name=op.f("uq__backoffice__document_revision__uid__person_uid")
        ),
    )
    op.create_table(
        "backoffice__raw_document_chunk",
        sa.Column("raw_document_uid", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_base64", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "byte_count > 0 AND byte_count <= 262144",
            name=op.f("ck__backoffice__raw_document_chunk__bounded_bytes"),
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name=op.f("ck__backoffice__raw_document_chunk__nonnegative_index")
        ),
        sa.CheckConstraint(
            "length(content_base64) <= 349528",
            name=op.f("ck__backoffice__raw_document_chunk__bounded_content"),
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name=op.f("ck__backoffice__raw_document_chunk__sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_document_uid"],
            ["backoffice__raw_document.uid"],
            name=op.f("fk__backoffice__raw_document_chunk__raw_document_uid_abb8a9f872"),
        ),
        sa.PrimaryKeyConstraint(
            "raw_document_uid", "chunk_index", name=op.f("pk__backoffice__raw_document_chunk")
        ),
    )
    op.create_table(
        "backoffice__reconciliation_evaluation",
        sa.Column("assignment_uid", sa.Uuid(), nullable=False),
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("person_revision", sa.Integer(), nullable=False),
        sa.Column("assignment_revision", sa.Integer(), nullable=False),
        sa.Column("set_key", sa.String(length=120), nullable=False),
        sa.Column("set_version", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck__backoffice__reconciliation_evaluation__allowed_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'failed') OR completed_at IS NOT NULL",
            name=op.f("ck__backoffice__reconciliation_evaluation__completion_time"),
        ),
        sa.CheckConstraint(
            "assignment_revision >= 1",
            name=op.f("ck__backoffice__reconciliation_evaluation__positive_revision"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_uid", "person_uid"],
            ["backoffice__person_document_set.uid", "backoffice__person_document_set.person_uid"],
            name=op.f("fk__backoffice__reconciliation_evaluation__assignmen_657981db03"),
        ),
        sa.ForeignKeyConstraint(
            ["person_uid", "person_revision"],
            ["backoffice__person_revision.person_uid", "backoffice__person_revision.revision"],
            name=op.f("fk__backoffice__reconciliation_evaluation__person_ui_e079520457"),
        ),
        sa.ForeignKeyConstraint(
            ["set_key", "set_version"],
            [
                "backoffice__document_set_version.set_key",
                "backoffice__document_set_version.version",
            ],
            name=op.f("fk__backoffice__reconciliation_evaluation__set_key_de1d49cfae"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__reconciliation_evaluation")),
        sa.UniqueConstraint(
            "operation_key", name=op.f("uq__backoffice__reconciliation_evaluation__operation_key")
        ),
    )
    op.create_index(
        op.f("ix__backoffice__reconciliation_evaluation__assignment_uid"),
        "backoffice__reconciliation_evaluation",
        ["assignment_uid"],
        unique=False,
    )
    op.create_table(
        "backoffice__document_review",
        sa.Column("document_uid", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("decision_sequence", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name=op.f("ck__backoffice__document_review__allowed_decision"),
        ),
        sa.CheckConstraint(
            "decision_sequence >= 1",
            name=op.f("ck__backoffice__document_review__positive_sequence"),
        ),
        sa.ForeignKeyConstraint(
            ["document_uid", "revision"],
            [
                "backoffice__document_revision.document_uid",
                "backoffice__document_revision.revision",
            ],
            name=op.f("fk__backoffice__document_review__document_uid__revis_d64c975914"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__document_review")),
        sa.UniqueConstraint(
            "document_uid",
            "revision",
            "decision_sequence",
            name=op.f("uq__backoffice__document_review__document_uid__revis_700508262e"),
        ),
        sa.UniqueConstraint(
            "operation_key", name=op.f("uq__backoffice__document_review__operation_key")
        ),
    )
    op.create_table(
        "backoffice__field_evidence",
        sa.Column("revision_uid", sa.Uuid(), nullable=False),
        sa.Column("person_uid", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=240), nullable=False),
        sa.Column("raw_document_uid", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "page_number >= 1", name=op.f("ck__backoffice__field_evidence__positive_page")
        ),
        sa.ForeignKeyConstraint(
            ["raw_document_uid", "person_uid"],
            ["backoffice__raw_document.uid", "backoffice__raw_document.person_uid"],
            name=op.f("fk__backoffice__field_evidence__raw_document_uid__pe_1aedc5df17"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_uid", "person_uid"],
            ["backoffice__document_revision.uid", "backoffice__document_revision.person_uid"],
            name=op.f("fk__backoffice__field_evidence__revision_uid__person_3df8984eb2"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__field_evidence")),
    )
    op.create_index(
        op.f("ix__backoffice__field_evidence__revision_uid"),
        "backoffice__field_evidence",
        ["revision_uid"],
        unique=False,
    )
    op.create_table(
        "backoffice__reconciliation_finding",
        sa.Column("evaluation_uid", sa.Uuid(), nullable=False),
        sa.Column("requirement_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("field_paths", sa.JSON(), nullable=False),
        sa.Column("document_references", sa.JSON(), nullable=False),
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('satisfied', 'missing', 'failed', 'pending_review', 'needs_information', 'not_applicable')",
            name=op.f("ck__backoffice__reconciliation_finding__allowed_status"),
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_uid"],
            ["backoffice__reconciliation_evaluation.uid"],
            name=op.f("fk__backoffice__reconciliation_finding__evaluation_u_54633657c3"),
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__backoffice__reconciliation_finding")),
    )
    op.create_index(
        op.f("ix__backoffice__reconciliation_finding__evaluation_uid"),
        "backoffice__reconciliation_finding",
        ["evaluation_uid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix__backoffice__reconciliation_finding__evaluation_uid"),
        table_name="backoffice__reconciliation_finding",
    )
    op.drop_table("backoffice__reconciliation_finding")
    op.drop_index(
        op.f("ix__backoffice__field_evidence__revision_uid"),
        table_name="backoffice__field_evidence",
    )
    op.drop_table("backoffice__field_evidence")
    op.drop_table("backoffice__document_review")
    op.drop_index(
        op.f("ix__backoffice__reconciliation_evaluation__assignment_uid"),
        table_name="backoffice__reconciliation_evaluation",
    )
    op.drop_table("backoffice__reconciliation_evaluation")
    op.drop_table("backoffice__raw_document_chunk")
    op.drop_table("backoffice__document_revision")
    op.drop_table("backoffice__assignment_document")
    op.drop_index(
        op.f("ix__backoffice__raw_document__person_uid"), table_name="backoffice__raw_document"
    )
    op.drop_table("backoffice__raw_document")
    op.drop_table("backoffice__person_revision")
    op.drop_index(
        op.f("ix__backoffice__person_document_set__person_uid"),
        table_name="backoffice__person_document_set",
    )
    op.drop_table("backoffice__person_document_set")
    op.drop_index(op.f("ix__backoffice__document__person_uid"), table_name="backoffice__document")
    op.drop_table("backoffice__document")
    op.drop_table("backoffice__processing_run")
    op.drop_table("backoffice__person")
    op.drop_table("backoffice__document_set_version")
    op.drop_table("backoffice__document_schema")
    op.drop_index(
        op.f("ix__backoffice__audit_event__resource_uid"), table_name="backoffice__audit_event"
    )
    op.drop_index(
        op.f("ix__backoffice__audit_event__correlation_uid"), table_name="backoffice__audit_event"
    )
    op.drop_table("backoffice__audit_event")
