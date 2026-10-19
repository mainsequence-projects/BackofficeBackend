"""Track independent staff reviewer memberships without changing subject ownership."""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0007"
down_revision = "backoffice_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backoffice__case_reviewer",
        sa.Column("assignment_uid", sa.Uuid(), nullable=False),
        sa.Column("reviewer_uid", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("assignment_uid", "reviewer_uid"),
        sa.ForeignKeyConstraint(["assignment_uid"], ["backoffice__person_document_set.uid"]),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
    )
    op.create_index("ix__backoffice__case_reviewer__active", "backoffice__case_reviewer", ["active"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM backoffice__case_reviewer")).scalar():
        raise RuntimeError("Retained reviewer memberships prevent downgrade")
    op.drop_index("ix__backoffice__case_reviewer__active", table_name="backoffice__case_reviewer")
    op.drop_table("backoffice__case_reviewer")
