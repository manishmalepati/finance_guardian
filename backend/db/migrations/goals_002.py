"""Move legacy parent category limits into the versioned monthly goal model."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "002_monthly_goals"


def upgrade(connection: Connection) -> None:
    connection.execute(text("""create table if not exists planning.goals (
        id uuid primary key,
        name varchar(120) not null,
        metric_type varchar(40) not null default 'monthly_spend',
        period_type varchar(30) not null default 'calendar_month',
        scope_kind varchar(20) not null,
        category_id varchar(50) not null references enrichment.category_taxonomy(category_id),
        threshold_amount numeric(12,2) not null,
        currency varchar(3) not null default 'USD',
        timezone varchar(64) not null default 'UTC',
        status varchar(20) not null default 'active',
        rule_version integer not null default 1,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        constraint uq_goal_metric_category unique (metric_type, category_id)
    )"""))
    connection.execute(text("""insert into planning.goals
        (id, name, metric_type, period_type, scope_kind, category_id,
         threshold_amount, currency, timezone, status, rule_version)
        select gen_random_uuid(), c.display_name || ' monthly limit',
               'monthly_spend', 'calendar_month', 'category', l.category_id,
               l.amount, 'USD', 'UTC', 'active', 1
        from planning.monthly_category_limits l
        join enrichment.category_taxonomy c on c.category_id = l.category_id
        on conflict (metric_type, category_id) do nothing
    """))
