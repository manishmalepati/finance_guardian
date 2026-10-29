"""Record explicit category choices separately from alias propagation."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "006_categorization_corrections"


def upgrade(connection: Connection) -> None:
    connection.execute(text("""create table if not exists enrichment.categorization_corrections (
        id uuid primary key,
        transaction_id uuid not null references core.transactions(id) on delete cascade,
        category_id varchar(50) not null references enrichment.category_taxonomy(category_id),
        source varchar(30) not null,
        created_at timestamptz not null default now()
    )"""))
    connection.execute(text("""create index if not exists ix_correction_transaction_date
        on enrichment.categorization_corrections (transaction_id, created_at desc)"""))
