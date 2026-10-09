"""Shared helpers for idempotent Alembic upgrades."""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


def table_exists(table: str) -> bool:
    return table in set(inspect(op.get_bind()).get_table_names())


def column_exists(table: str, column: str) -> bool:
    if not table_exists(table):
        return False
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns(table)}
    return column in columns


def index_exists(table: str, index_name: str) -> bool:
    if not table_exists(table):
        return False
    indexes = {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}
    return index_name in indexes


def unique_constraint_exists(table: str, constraint_name: str) -> bool:
    if not table_exists(table):
        return False
    constraints = {
        uq["name"]
        for uq in inspect(op.get_bind()).get_unique_constraints(table)
        if uq.get("name")
    }
    return constraint_name in constraints


def fk_exists(table: str, fk_name: str) -> bool:
    if not table_exists(table):
        return False
    foreign_keys = {
        fk["name"]
        for fk in inspect(op.get_bind()).get_foreign_keys(table)
        if fk.get("name")
    }
    return fk_name in foreign_keys


def enum_exists(enum_name: str) -> bool:
    result = op.get_bind().execute(
        text("SELECT 1 FROM pg_type WHERE typname = :enum_name"),
        {"enum_name": enum_name},
    )
    return result.scalar() is not None


def enum_value_exists(enum_name: str, value: str) -> bool:
    result = op.get_bind().execute(
        text(
            """
            SELECT 1
            FROM pg_enum e
            JOIN pg_type t ON e.enumtypid = t.oid
            WHERE t.typname = :enum_name AND e.enumlabel = :value
            """
        ),
        {"enum_name": enum_name, "value": value},
    )
    return result.scalar() is not None
