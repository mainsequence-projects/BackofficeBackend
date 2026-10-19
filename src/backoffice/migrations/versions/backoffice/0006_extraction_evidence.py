"""Bind extraction observations to exact revisions and support JSON Pointer paths."""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0006"
down_revision = "backoffice_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "backoffice__document_revision", sa.Column("extraction_evidence", sa.JSON(), nullable=True)
    )
    with op.batch_alter_table("backoffice__field_evidence") as batch:
        batch.alter_column(
            "field_path",
            existing_type=sa.String(240),
            type_=sa.String(500),
            existing_nullable=False,
        )


def downgrade():
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text(
                "SELECT count(*) FROM backoffice__document_revision "
                "WHERE extraction_evidence IS NOT NULL AND CAST(extraction_evidence AS TEXT) != 'null'"
            )
        ).scalar()
        or connection.execute(
            sa.text(
                "SELECT count(*) FROM backoffice__field_evidence WHERE length(field_path) > 240"
            )
        ).scalar()
    ):
        raise RuntimeError("Retained extraction evidence prevents downgrade")
    with op.batch_alter_table("backoffice__field_evidence") as batch:
        batch.alter_column(
            "field_path",
            existing_type=sa.String(500),
            type_=sa.String(240),
            existing_nullable=False,
        )
    with op.batch_alter_table("backoffice__document_revision") as batch:
        batch.drop_column("extraction_evidence")
