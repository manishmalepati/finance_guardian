select distinct
    coalesce(account_id::text, md5(account_name)) as account_id,
    account_name
from {{ ref('stg_transactions') }}
