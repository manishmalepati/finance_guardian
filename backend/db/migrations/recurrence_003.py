"""Persist user review of recurring-charge candidates without changing ledger rows."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "003_recurring_reviews"


def upgrade(connection: Connection) -> None:
    connection.execute(text("""create table if not exists analytics.recurring_reviews (
        series_key varchar(64) primary key,
        decision varchar(20) not null,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        constraint ck_recurring_review_decision
            check (decision in ('confirmed', 'not_recurring'))
    )"""))
