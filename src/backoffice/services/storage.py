"""Governed MetaTables SQL. Only tests provide an alternative executor."""

import json
from datetime import UTC, datetime
from uuid import UUID

from metatables import MetaTable
from metatables.compiled_sql.v1 import compile_sqlalchemy_statement
from pydantic_core import to_jsonable_python
from sqlalchemy import JSON, DateTime, Uuid, and_, exists, func, insert, literal, select, update

from ..tables import metatable_models

TABLES = {model.__tablename__: model.__table__ for model in metatable_models()}


def wire(value):
    return to_jsonable_python(value)


def typed(table, values):
    result = dict(values)
    for key, value in values.items():
        if value is None:
            continue
        kind = table.c[key].type
        if isinstance(kind, Uuid):
            result[key] = UUID(str(value))
        elif isinstance(kind, DateTime) and isinstance(value, str):
            result[key] = (
                datetime.fromisoformat(value).replace(tzinfo=UTC)
                if "+" not in value and not value.endswith("Z")
                else datetime.fromisoformat(value)
            )
    return result


def decode(table, row):
    row = dict(row)
    for key, value in row.items():
        if value is None or key not in table.c:
            continue
        kind = table.c[key].type
        if isinstance(kind, JSON) and isinstance(value, str):
            row[key] = json.loads(value)
        elif isinstance(kind, Uuid):
            row[key] = str(UUID(str(value)))
        elif isinstance(kind, DateTime):
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
            row[key] = (
                parsed.replace(tzinfo=UTC).isoformat()
                if parsed.tzinfo is None
                else parsed.isoformat()
            )
    return wire(row)


class Storage:
    def __init__(self):
        self.context = None

    def execute(self, statement, operation="select"):
        if self.context is None:
            from metatables.runtime_context import get_runtime_context

            self.context = get_runtime_context()
        # A runtime switch must fail admission, never split a request's writes
        # across databases. The API validates this pinned source on every call.
        payload = compile_sqlalchemy_statement(
            statement,
            operation=operation,
            data_source_uid=self.context.require_data_source_uid(),
            dialect=self.context.require_sql_dialect()[0],
            limits={"max_rows": 501, "statement_timeout_ms": 15000},
        )
        # The compiler preserves native JSON values for this wire dialect.
        # Text SQL bindings need JSON text for the server's driver.
        if payload.dialect == "postgresql":
            payload.statement.parameters = {
                k: json.dumps(v) if isinstance(v, (dict, list)) else v
                for k, v in payload.statement.parameters.items()
            }
        return MetaTable.execute_operation(payload, timeout=25)

    def rows(self, table, *conditions, limit=200, offset=0, order=None):
        statement = select(table).where(*conditions).limit(limit).offset(offset)
        if order is not None:
            statement = statement.order_by(*(order if isinstance(order, tuple) else (order,)))
        result = self.execute(statement)
        rows = result.get("rows", [])
        if result.get("pagination", {}).get("has_more") and len(rows) < limit:
            raise RuntimeError("MetaTables returned an incomplete bounded result")
        return [decode(table, row) for row in rows]

    def count(self, table, *conditions):
        result = self.execute(
            select(func.count().label("total")).select_from(table).where(*conditions)
        )
        return int(result["rows"][0]["total"])

    def page(self, table, *conditions, limit=50, offset=0, order=None):
        items = self.rows(table, *conditions, limit=limit, offset=offset, order=order)
        total = self.count(table, *conditions)
        return {
            "items": items,
            "total_items": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total,
        }

    def one(self, table, **keys):
        keys = typed(table, keys)
        rows = self.rows(table, *(table.c[key] == value for key, value in keys.items()), limit=1)
        return rows[0] if rows else None

    def ensure(self, table, values):
        values = typed(table, values)
        keys = {col.name: values[col.name] for col in table.primary_key}
        present = self.one(table, **keys)
        if present is None:
            # Atomic insert-if-absent: retries cannot overwrite immutable content.
            predicate = and_(*(table.c[key] == value for key, value in keys.items()))
            statement = insert(table).from_select(
                list(values),
                select(
                    *(literal(value, type_=table.c[key].type) for key, value in values.items())
                ).where(~exists(select(1).select_from(table).where(predicate))),
            )
            self.execute(statement, "insert")
            present = self.one(table, **keys)
        return present

    def change(self, table, keys, values, expected=None):
        keys, values = typed(table, keys), typed(table, values)
        conditions = [table.c[key] == value for key, value in keys.items()]
        conditions += [table.c[key] == value for key, value in typed(table, expected or {}).items()]
        self.execute(update(table).where(*conditions).values(**values), "update")
        present = self.one(table, **keys)
        return present
