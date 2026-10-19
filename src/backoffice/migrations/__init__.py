from __future__ import annotations

from metatables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)

from src.backoffice.tables import Base, metatable_models

BackofficeAlembicVersion = build_alembic_version_metatable(
    class_name="BackofficeAlembicVersion",
    namespace="backoffice",
    identifier="backoffice.alembic_version",
    schema="public",
    table_name="backoffice__alembic_version",
)

migration = build_metatable_migration_provider(
    package="src.backoffice",
    migration_namespace="backoffice",
    script_location="src.backoffice.migrations:",
    version_location_prefix="src.backoffice.migrations:versions",
    target_metadata=Base.metadata,
    alembic_registry=BackofficeAlembicVersion,
    metatable_models=metatable_models(),
)


__all__ = ["BackofficeAlembicVersion", "migration"]
