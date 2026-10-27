"""Receipt tables are additive; core transactions remain the money ledger."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "001_receipts"


def upgrade(connection: Connection) -> None:
    statements = [
        """create table receipt.gmail_connections (
            id uuid primary key, email_address text not null unique,
            encrypted_refresh_token text not null,
            status varchar(30) not null default 'active',
            last_sync_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )""",
        """create table receipt.oauth_states (
            state text primary key, code_verifier text not null,
            expires_at timestamptz not null
        )""",
        """create table receipt.sync_runs (
            id uuid primary key,
            connection_id uuid not null references receipt.gmail_connections(id),
            status varchar(30) not null,
            discovered_count integer not null default 0,
            imported_count integer not null default 0,
            skipped_count integer not null default 0,
            failed_count integer not null default 0,
            error_code varchar(100),
            started_at timestamptz not null default now(),
            completed_at timestamptz
        )""",
        """create table receipt.email_sources (
            id uuid primary key,
            connection_id uuid not null references receipt.gmail_connections(id),
            gmail_message_id text not null,
            sender text, subject text, received_at timestamptz,
            parse_status varchar(30) not null,
            error_code varchar(100), parser_version varchar(30) not null,
            created_at timestamptz not null default now(),
            unique (connection_id, gmail_message_id)
        )""",
        """create table receipt.orders (
            id uuid primary key,
            email_source_id uuid not null references receipt.email_sources(id) on delete cascade,
            order_index integer not null default 0,
            merchant text not null, merchant_order_id text,
            placed_at timestamptz, placed_date date, currency varchar(10),
            subtotal numeric(12,2), delivery_fee numeric(12,2),
            tax numeric(12,2), tip numeric(12,2),
            other_fees numeric(12,2), discount numeric(12,2),
            total numeric(12,2), parse_quality varchar(30) not null,
            unique (email_source_id, order_index)
        )""",
        """create table receipt.order_items (
            id uuid primary key,
            order_id uuid not null references receipt.orders(id) on delete cascade,
            position integer not null, description text not null,
            quantity numeric(12,3), unit_price numeric(12,2),
            line_total numeric(12,2), category_id varchar(50),
            evidence text, unique (order_id, position)
        )""",
        """create table receipt.transaction_order_matches (
            id uuid primary key,
            transaction_id uuid not null references core.transactions(id),
            order_id uuid not null references receipt.orders(id),
            status varchar(30) not null,
            confidence numeric(4,3) not null,
            reasons jsonb not null default '[]'::jsonb,
            user_override boolean not null default false,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (transaction_id, order_id)
        )""",
        "create index ix_receipt_matches_transaction on receipt.transaction_order_matches(transaction_id)",
        "create index ix_receipt_orders_placed_at on receipt.orders(placed_at)",
    ]
    for statement in statements:
        connection.execute(text(statement))
