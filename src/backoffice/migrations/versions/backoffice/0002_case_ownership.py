"""Add trusted case ownership without rewriting history."""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0002"
down_revision = "backoffice_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("backoffice__person", sa.Column("created_by", sa.Uuid(), nullable=True))


def downgrade():
    op.drop_column("backoffice__person", "created_by")
