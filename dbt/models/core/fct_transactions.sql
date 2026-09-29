select
    transaction_id,
    md5(account_name) as account_id,
    md5(category) as category_id,
    md5(upper(description)) as merchant_id,
    posted_date,
    description,
    amount,
    case when direction = 'debit' then amount else -amount end as signed_amount,
    direction,
    source,
    created_at
from {{ ref('stg_chase_transactions') }}
