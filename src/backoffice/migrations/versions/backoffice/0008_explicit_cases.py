"""Promote assignments to business cases, preserving every existing reference."""

import sqlalchemy as sa
from alembic import op

revision = "backoffice_0008"
down_revision = "backoffice_0007"
branch_labels = None
depends_on = None


def upgrade():
    # Freeze these definitions here; future catalog edits must not rewrite migration history.
    types = sa.Table(
        "backoffice__case_type",
        sa.MetaData(),
        sa.Column("key", sa.String(80)),
        sa.Column("name", sa.String(160)),
        sa.Column("description", sa.String(500)),
    )
    op.create_table(
        types.name,
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
    )
    op.bulk_insert(
        types,
        [
            {
                "key": "account_opening",
                "name": "Account opening",
                "description": "Prepare and review the evidence required to open an account.",
            },
            {
                "key": "new_loan",
                "name": "New loan",
                "description": "Prepare and review the evidence required for a new loan application.",
            },
            {
                "key": "document_review",
                "name": "Document review",
                "description": "Review evidence against a published requirement set, including preserved legacy cases.",
            },
        ],
    )
    op.create_table(
        "backoffice__case_type_document_set",
        sa.Column("case_type_key", sa.String(80), nullable=False),
        sa.Column("set_key", sa.String(120), nullable=False),
        sa.Column("set_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("case_type_key", "set_key", "set_version"),
        sa.ForeignKeyConstraint(["case_type_key"], ["backoffice__case_type.key"]),
        sa.ForeignKeyConstraint(
            ["set_key", "set_version"],
            [
                "backoffice__document_set_version.set_key",
                "backoffice__document_set_version.version",
            ],
        ),
    )
    policies = sa.table(
        "backoffice__document_set_version",
        sa.column("set_key", sa.String()),
        sa.column("version", sa.Integer()),
    )
    bindings = sa.table(
        "backoffice__case_type_document_set",
        sa.column("case_type_key"),
        sa.column("set_key"),
        sa.column("set_version"),
    )
    process = sa.case(
        (policies.c.set_key == "new_account_requirements", "account_opening"),
        (policies.c.set_key == "loan_requirements", "new_loan"),
        else_="document_review",
    )
    op.execute(
        bindings.insert().from_select(
            ["case_type_key", "set_key", "set_version"],
            sa.select(process, policies.c.set_key, policies.c.version),
        )
    )
    # Additive rollout: old releases and retained intents may still insert without this column.
    op.add_column(
        "backoffice__person_document_set", sa.Column("case_type_key", sa.String(80), nullable=True)
    )
    cases = sa.table(
        "backoffice__person_document_set", sa.column("set_key"), sa.column("case_type_key")
    )
    op.execute(
        cases.update().values(
            case_type_key=sa.case(
                (cases.c.set_key == "new_account_requirements", "account_opening"),
                (cases.c.set_key == "loan_requirements", "new_loan"),
                else_="document_review",
            )
        )
    )
    with op.batch_alter_table(cases.name) as batch:
        batch.create_foreign_key("fk_case_type", types.name, ["case_type_key"], ["key"])
        batch.create_foreign_key(
            "fk_case_permitted_document_set",
            bindings.name,
            ["case_type_key", "set_key", "set_version"],
            ["case_type_key", "set_key", "set_version"],
        )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM backoffice__person_document_set"))
        .scalar()
    ):
        raise RuntimeError("Retained business cases prevent downgrade")
    with op.batch_alter_table("backoffice__person_document_set") as batch:
        batch.drop_constraint("fk_case_permitted_document_set", type_="foreignkey")
        batch.drop_constraint("fk_case_type", type_="foreignkey")
        batch.drop_column("case_type_key")
    op.drop_table("backoffice__case_type_document_set")
    op.drop_table("backoffice__case_type")
