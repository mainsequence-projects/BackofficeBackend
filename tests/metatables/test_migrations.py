"""Physical migration verification in a disposable database, never a hosted runtime."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from metatables.migrations import alembic_config_for_provider
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from src.backoffice.migrations import migration
from src.backoffice.tables import Base, metatable_models
from src.backoffice.tables.documents import (
    DocumentRecord,
    DocumentReviewRecord,
    DocumentRevisionRecord,
)
from src.backoffice.tables.evidence import RawDocumentChunkRecord, RawDocumentRecord
from src.backoffice.tables.person import PersonRecord
from src.backoffice.tables.requirements import (
    AssignmentDocumentRecord,
    DocumentSchemaRecord,
    DocumentSetVersionRecord,
    PersonDocumentSetRecord,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def migrated():
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        config = alembic_config_for_provider(migration, sqlalchemy_url="sqlite://")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        yield connection, config
    engine.dispose()


def test_migration_round_trip_matches_models_and_preserves_existing_rows(migrated):
    connection, config = migrated
    uid = uuid4()
    connection.execute(
        PersonRecord.__table__.insert().values(
            uid=uid, current_revision=1, profile={}, created_at=NOW, updated_at=NOW
        )
    )
    connection.commit()
    command.upgrade(config, "head")
    assert connection.execute(PersonRecord.__table__.select()).one().uid == uid
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                name != migration.version_table
            )
        },
    )
    assert compare_metadata(context, Base.metadata) == []
    assert (
        connection.exec_driver_sql(
            "SELECT version_num FROM backoffice__alembic_version"
        ).scalar_one()
        == "backoffice_0004"
    )
    connection.rollback()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.commit()
    command.downgrade(config, "base")
    assert inspect(connection).get_table_names() == ["backoffice__alembic_version"]
    command.upgrade(config, "head")
    assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
        "backoffice__alembic_version"
    }


def test_all_registration_contracts_and_column_metadata_are_valid():
    models = metatable_models()
    assert len(models) == len({model.__metatable_identifier__ for model in models}) == 18
    for model in models:
        assert model.__metatable_namespace__ == "backoffice"
        assert len(model.__metatable_description__) <= 500
        assert 2 <= len(model.__metatable_labels__) <= 6
        request = model.build_registration_request(data_source_uid=str(uuid4()))
        assert request.identifier == model.__metatable_identifier__
        for column in model.__table__.columns:
            assert 1 <= len(column.info["label"].split()) <= 4
            assert len(column.info["description"]) >= 15


def seed_documents(connection):
    person, other_person, document, assignment = (uuid4() for _ in range(4))
    for uid in (person, other_person):
        connection.execute(
            PersonRecord.__table__.insert().values(
                uid=uid, current_revision=1, profile={}, created_at=NOW, updated_at=NOW
            )
        )
    connection.execute(
        DocumentSchemaRecord.__table__.insert().values(
            document_type="passport",
            version=1,
            canonical_schema={},
            draft_schema={},
            content_sha256="a" * 64,
            created_at=NOW,
        )
    )
    connection.execute(
        DocumentSetVersionRecord.__table__.insert().values(
            set_key="onboarding",
            version=1,
            definition={},
            status="published",
            published_at=NOW,
            created_at=NOW,
        )
    )
    connection.execute(
        PersonDocumentSetRecord.__table__.insert().values(
            uid=assignment,
            person_uid=person,
            set_key="onboarding",
            set_version=1,
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    connection.execute(
        DocumentRecord.__table__.insert().values(
            uid=document,
            person_uid=person,
            document_type="passport",
            current_revision=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    connection.commit()
    return person, other_person, document, assignment


def test_membership_requires_same_person_and_is_unique(migrated):
    connection, _ = migrated
    person, other, document, assignment = seed_documents(connection)
    row = dict(assignment_uid=assignment, document_uid=document, person_uid=person)
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            AssignmentDocumentRecord.__table__.insert().values(**dict(row, person_uid=other))
        )
    connection.execute(AssignmentDocumentRecord.__table__.insert().values(**row))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(AssignmentDocumentRecord.__table__.insert().values(**row))


def test_revision_requires_registered_schema_and_review_requires_exact_revision(migrated):
    connection, _ = migrated
    person, _, document, _ = seed_documents(connection)
    row = dict(
        uid=uuid4(),
        document_uid=document,
        person_uid=person,
        document_type="passport",
        revision=1,
        schema_version=1,
        payload={},
        raw_document_refs=[],
        status="submitted",
        submitted_at=NOW,
        created_at=NOW,
        created_by=uuid4(),
    )
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            DocumentRevisionRecord.__table__.insert().values(**dict(row, schema_version=2))
        )
    connection.execute(DocumentRevisionRecord.__table__.insert().values(**row))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            DocumentRevisionRecord.__table__.insert().values(**dict(row, uid=uuid4()))
        )
    review = dict(
        uid=uuid4(),
        document_uid=document,
        revision=1,
        decision_sequence=1,
        decision="accepted",
        reviewed_by=uuid4(),
        reviewed_at=NOW,
        reason="Checked",
        operation_key=uuid4(),
    )
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            DocumentReviewRecord.__table__.insert().values(**dict(review, revision=2))
        )
    connection.execute(DocumentReviewRecord.__table__.insert().values(**review))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            DocumentReviewRecord.__table__.insert().values(
                **dict(review, uid=uuid4(), decision_sequence=2)
            )
        )


def test_raw_chunk_bounds_and_upload_finalization_state(migrated):
    connection, _ = migrated
    person, *_ = seed_documents(connection)
    source = uuid4()
    row = dict(
        uid=source,
        person_uid=person,
        operation_key=uuid4(),
        filename="example.pdf",
        media_type="application/pdf",
        byte_count=1,
        content_sha256="a" * 64,
        chunk_count=1,
        status="ready",
        created_at=NOW,
        finalized_at=None,
    )
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(RawDocumentRecord.__table__.insert().values(**row))
    connection.execute(RawDocumentRecord.__table__.insert().values(**dict(row, status="uploading")))
    chunk = dict(
        raw_document_uid=source,
        chunk_index=0,
        content_base64="YQ==",
        byte_count=1,
        content_sha256="b" * 64,
    )
    for bad in (dict(chunk, byte_count=262145), dict(chunk, chunk_index=-1)):
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(RawDocumentChunkRecord.__table__.insert().values(**bad))
    connection.execute(RawDocumentChunkRecord.__table__.insert().values(**chunk))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(RawDocumentChunkRecord.__table__.insert().values(**chunk))


def test_per_type_migration_preserves_global_policy_history():
    from src.backoffice.tables.parsing import ParsingPolicyRecord

    engine = create_engine("sqlite://")
    uid = uuid4()
    with engine.connect() as connection:
        config = alembic_config_for_provider(migration, sqlalchemy_url="sqlite://")
        config.attributes["connection"] = connection
        command.upgrade(config, "backoffice_0003")
        connection.execute(
            ParsingPolicyRecord.__table__.insert().values(
                uid=uid,
                created_at=NOW,
                settings_key="document_parsing",
                revision=7,
                automatic_acceptance_enabled=True,
                threshold_basis_points=6000,
                changed_by=uuid4(),
                operation_key=uuid4(),
            )
        )
        connection.commit()
        command.upgrade(config, "head")
        row = connection.execute(ParsingPolicyRecord.__table__.select()).one()
        assert row.uid == uid and row.revision == 7 and row.threshold_basis_points == 6000
        assert row.document_type is None
        command.upgrade(config, "head")
        assert len(connection.execute(ParsingPolicyRecord.__table__.select()).all()) == 1
    engine.dispose()


def test_parsing_policy_constraints_bound_scores_and_scope_revisions(migrated):
    from src.backoffice.tables.parsing import ParsingPolicyRecord

    connection, _ = migrated
    table = ParsingPolicyRecord.__table__
    row = dict(
        uid=uuid4(),
        created_at=NOW,
        settings_key="document_parsing:passport",
        document_type="passport",
        revision=1,
        automatic_acceptance_enabled=True,
        threshold_basis_points=6000,
        changed_by=uuid4(),
        operation_key=uuid4(),
    )
    connection.execute(table.insert().values(**row))
    connection.execute(
        table.insert().values(
            **{
                **row,
                "uid": uuid4(),
                "operation_key": uuid4(),
                "document_type": "bank_statement",
                "settings_key": "document_parsing:bank_statement",
                "threshold_basis_points": 9000,
            }
        )
    )
    for changes in (
        {"revision": 2, "threshold_basis_points": -1},
        {"revision": 2, "threshold_basis_points": 10001},
        {"revision": 2, "threshold_basis_points": None},
        {"revision": 0},
        {"settings_key": "other-key"},
    ):
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                table.insert().values(
                    **{
                        **row,
                        "uid": uuid4(),
                        "operation_key": uuid4(),
                        **changes,
                    }
                )
            )
