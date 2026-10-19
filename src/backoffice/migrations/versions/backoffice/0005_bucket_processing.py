"""Add private bucket sources and fenced extraction worker claims."""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0005"
down_revision = "backoffice_0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("backoffice__raw_document") as batch:
        batch.add_column(
            sa.Column("storage_kind", sa.String(16), nullable=False, server_default="chunks")
        )
        batch.add_column(sa.Column("bucket_name", sa.String(120), nullable=True))
        batch.add_column(sa.Column("artifact_uid", sa.Uuid(), nullable=True))
        batch.drop_constraint(op.f("ck__backoffice__raw_document__positive_chunks"), type_="check")
        batch.create_check_constraint(
            "source_storage",
            "(storage_kind = 'chunks' AND chunk_count > 0) OR (storage_kind = 'bucket' AND chunk_count = 0 AND bucket_name IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ready_bucket_object",
            "storage_kind != 'bucket' OR status != 'ready' OR artifact_uid IS NOT NULL",
        )
    with op.batch_alter_table("backoffice__processing_run") as batch:
        batch.add_column(sa.Column("lease_token", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.drop_constraint(op.f("ck__backoffice__processing_run__allowed_status"), type_="check")
        batch.create_check_constraint(
            "allowed_status",
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'needs_input')",
        )


def downgrade():
    # A downgrade cannot discard bucket evidence or unresolved processing runs.
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text("SELECT count(*) FROM backoffice__raw_document WHERE storage_kind = 'bucket'")
        ).scalar()
        or connection.execute(
            sa.text("SELECT count(*) FROM backoffice__processing_run WHERE status = 'needs_input'")
        ).scalar()
    ):
        raise RuntimeError("Bucket evidence or unresolved runs prevent downgrade")
    with op.batch_alter_table("backoffice__processing_run") as batch:
        batch.drop_constraint(op.f("ck__backoffice__processing_run__allowed_status"), type_="check")
        batch.create_check_constraint(
            "allowed_status", "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')"
        )
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_token")
    with op.batch_alter_table("backoffice__raw_document") as batch:
        batch.drop_constraint(
            op.f("ck__backoffice__raw_document__ready_bucket_object"), type_="check"
        )
        batch.drop_constraint(op.f("ck__backoffice__raw_document__source_storage"), type_="check")
        batch.create_check_constraint("positive_chunks", "chunk_count > 0")
        batch.drop_column("artifact_uid")
        batch.drop_column("bucket_name")
        batch.drop_column("storage_kind")
