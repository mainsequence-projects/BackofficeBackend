"""Add versioned parsing policy and exact-revision parsing results."""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0003"
down_revision = "backoffice_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backoffice__parsing_policy",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settings_key", sa.String(80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("automatic_acceptance_enabled", sa.Boolean(), nullable=False),
        sa.Column("threshold_basis_points", sa.Integer(), nullable=True),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("uid"),
        sa.UniqueConstraint("settings_key", "revision"),
        sa.UniqueConstraint("operation_key"),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint(
            "threshold_basis_points IS NULL OR threshold_basis_points BETWEEN 0 AND 10000",
            name="threshold_range",
        ),
        sa.CheckConstraint(
            "NOT automatic_acceptance_enabled OR threshold_basis_points IS NOT NULL",
            name="enabled_requires_threshold",
        ),
    )
    op.create_table(
        "backoffice__parsing_result",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_uid", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("score_basis_points", sa.Integer(), nullable=True),
        sa.Column("policy_uid", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("review_uid", sa.Uuid(), nullable=True),
        sa.Column("extractor", sa.String(120), nullable=False),
        sa.Column("processed_by", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("uid"),
        sa.UniqueConstraint("document_uid", "revision"),
        sa.UniqueConstraint("operation_key"),
        sa.ForeignKeyConstraint(
            ["document_uid", "revision"],
            [
                "backoffice__document_revision.document_uid",
                "backoffice__document_revision.revision",
            ],
        ),
        sa.ForeignKeyConstraint(["policy_uid"], ["backoffice__parsing_policy.uid"]),
        sa.ForeignKeyConstraint(["review_uid"], ["backoffice__document_review.uid"]),
        sa.CheckConstraint(
            "score_basis_points IS NULL OR score_basis_points BETWEEN 0 AND 10000",
            name="score_range",
        ),
        sa.CheckConstraint("decision IN ('accepted', 'needs_review')", name="allowed_decision"),
        sa.CheckConstraint(
            "(decision = 'accepted' AND review_uid IS NOT NULL) OR (decision = 'needs_review' AND review_uid IS NULL)",
            name="acceptance_reference",
        ),
    )


def downgrade():
    op.drop_table("backoffice__parsing_result")
    op.drop_table("backoffice__parsing_policy")
