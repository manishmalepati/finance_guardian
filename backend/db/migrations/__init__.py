"""Additive schema migrations for the local database."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.db.migrations import receipts_001


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("create schema if not exists receipt"))
        connection.execute(text(
            "create table if not exists receipt.schema_migrations "
            "(version varchar(100) primary key, applied_at timestamptz not null default now())"
        ))
        applied = connection.scalar(
            text("select 1 from receipt.schema_migrations where version = :version"),
            {"version": receipts_001.VERSION},
        )
        if not applied:
            receipts_001.upgrade(connection)
            connection.execute(
                text("insert into receipt.schema_migrations (version) values (:version)"),
                {"version": receipts_001.VERSION},
            )
