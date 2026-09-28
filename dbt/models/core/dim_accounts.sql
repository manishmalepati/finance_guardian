select distinct
    md5(account_name) as account_id,
    account_name
from {{ ref('stg_chase_transactions') }}
