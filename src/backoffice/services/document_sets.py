"""Human-admin publication of new requirement sets through the shared intent journal."""

from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from ..models.document_set import DocumentSet
from .application import SETS, fail
from .cases import BINDINGS, TYPES
from .contracts import Command


class CreateDocumentSet(Command):
    definition: DocumentSet
    case_type_keys: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def new_set(self):
        import re

        if not re.fullmatch(r"[a-z][a-z0-9_]{0,119}", self.definition.key):
            raise ValueError("Set key must use lowercase letters, numbers and underscores")
        if self.definition.version != 1:
            raise ValueError("A new document set starts at version 1")
        if len(self.case_type_keys) != len(set(self.case_type_keys)):
            raise ValueError("Choose each case type once")
        return self


def create(app, command):
    if not app.organization_admin:
        fail(403, "organization_admin_required")
    definition = command.definition.model_dump(mode="json")
    scope = str(uuid5(NAMESPACE_URL, f"backoffice:document-set:{definition['key']}"))

    def build(op, now):
        if app.db.rows(SETS, SETS.c.set_key == definition["key"], limit=1):
            fail(409, "document_set_key_already_exists_choose_a_new_key")
        for key in command.case_type_keys:
            if app.db.one(TYPES, key=key) is None:
                fail(422, "case_type_not_found")
        steps = [
            app.ensure_step(
                SETS,
                {
                    "set_key": definition["key"],
                    "version": 1,
                    "definition": definition,
                    "status": "published",
                    "published_at": now,
                    "created_at": now,
                },
            )
        ]
        steps.extend(
            app.ensure_step(
                BINDINGS,
                {
                    "case_type_key": key,
                    "set_key": definition["key"],
                    "set_version": 1,
                },
            )
            for key in command.case_type_keys
        )
        return steps, definition

    return app.mutate(
        scope,
        command,
        "admin.document_set_created",
        build,
        create=True,
        resource_type="document_set",
    )
