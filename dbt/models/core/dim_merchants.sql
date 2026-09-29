select distinct
    md5(upper(description)) as merchant_id,
    upper(description) as merchant_name
from {{ ref('stg_chase_transactions') }}
