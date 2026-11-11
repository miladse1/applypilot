"""Additive schema upgrades.

Creates missing tables and adds missing nullable columns. It never drops or
rewrites data, so it is safe to run on every start against SQLite or PostgreSQL.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.models import Base

log = logging.getLogger(__name__)


def _default_sql(column) -> str:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return ""
    value = default.arg
    if isinstance(value, bool):
        return f" DEFAULT {'TRUE' if value else 'FALSE'}"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def upgrade_connection(connection: Connection) -> list[str]:
    Base.metadata.create_all(connection)
    inspector = inspect(connection)
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            column_type = column.type.compile(dialect=connection.dialect)
            connection.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}{_default_sql(column)}'))
            added.append(f"{table.name}.{column.name}")
        for index in table.indexes:
            if all(col.name in existing for col in index.columns):
                continue
            try:
                index.create(connection, checkfirst=True)
            except Exception:  # noqa: BLE001 - an index is an optimization, not a requirement
                log.warning("Could not create index %s", index.name)
    return added


def ensure_schema(engine: Engine) -> list[str]:
    with engine.begin() as connection:
        added = upgrade_connection(connection)
    if added:
        log.info("Added columns: %s", ", ".join(added))
    return added
