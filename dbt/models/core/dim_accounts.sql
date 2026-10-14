select
    id::text as account_id,
    name as account_name,
    source,
    account_type,
    mask,
    iso_currency_code
from {{ source('core', 'financial_accounts') }}
