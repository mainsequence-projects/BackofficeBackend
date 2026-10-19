"""Scope parsing acceptance policy revisions to canonical document types.

Existing global rows retain a null type for historical result provenance. New
completions select an exact non-null document type and never fall back to them.
"""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0004"
down_revision = "backoffice_0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("backoffice__parsing_policy") as batch:
        batch.add_column(sa.Column("document_type", sa.String(80), nullable=True))
        batch.create_unique_constraint(
            op.f("uq__backoffice__parsing_policy__document_type__revision"),
            ["document_type", "revision"],
        )


def downgrade():
    with op.batch_alter_table("backoffice__parsing_policy") as batch:
        batch.drop_constraint(
            op.f("uq__backoffice__parsing_policy__document_type__revision"), type_="unique"
        )
        batch.drop_column("document_type")
