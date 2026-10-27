"""Additive schema migrations for the local database."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.db.migrations import goals_002, receipts_001, recurrence_003


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
    with engine.begin() as connection:
        connection.execute(text(
            "create table if not exists planning.schema_migrations "
            "(version varchar(100) primary key, applied_at timestamptz not null default now())"
        ))
        applied = connection.scalar(
            text("select 1 from planning.schema_migrations where version = :version"),
            {"version": goals_002.VERSION},
        )
        if not applied:
            goals_002.upgrade(connection)
            connection.execute(
                text("insert into planning.schema_migrations (version) values (:version)"),
                {"version": goals_002.VERSION},
            )
    with engine.begin() as connection:
        connection.execute(text("create schema if not exists analytics"))
        connection.execute(text(
            "create table if not exists analytics.schema_migrations "
            "(version varchar(100) primary key, applied_at timestamptz not null default now())"
        ))
        applied = connection.scalar(
            text("select 1 from analytics.schema_migrations where version = :version"),
            {"version": recurrence_003.VERSION},
        )
        if not applied:
            recurrence_003.upgrade(connection)
            connection.execute(
                text("insert into analytics.schema_migrations (version) values (:version)"),
                {"version": recurrence_003.VERSION},
            )
