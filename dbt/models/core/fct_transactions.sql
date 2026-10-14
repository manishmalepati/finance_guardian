select
    transaction_id,
    account_id::text as account_id,
    category_id,
    parent_category_id,
    md5(upper(merchant_name)) as merchant_id,
    posted_date,
    description,
    merchant_name,
    amount,
    case when direction = 'debit' then amount else -amount end as signed_amount,
    direction,
    status,
    is_pending,
    categorization_source,
    categorization_confidence,
    source,
    created_at
from {{ ref('stg_transactions') }}
