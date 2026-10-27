"""Persist user judgment of ranked charges without changing canonical transactions."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "004_anomaly_reviews"


def upgrade(connection: Connection) -> None:
    connection.execute(text("""create table if not exists analytics.anomaly_reviews (
        transaction_id uuid primary key references core.transactions(id) on delete cascade,
        decision varchar(20) not null,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        constraint ck_anomaly_review_decision check (decision in ('expected', 'unexpected'))
    )"""))
