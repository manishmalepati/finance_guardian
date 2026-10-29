"""Add durable reviews for multi-grain anomaly alerts."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "005_behavioral_alert_reviews"


def upgrade(connection: Connection) -> None:
    connection.execute(text("""create table if not exists analytics.behavioral_alert_reviews (
        alert_id varchar(64) primary key,
        decision varchar(20) not null,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        constraint ck_behavioral_review_decision check (decision in ('expected', 'unexpected'))
    )"""))
