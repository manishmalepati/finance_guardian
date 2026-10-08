select distinct
    md5(upper(merchant_name)) as merchant_id,
    merchant_name
from {{ ref('stg_transactions') }}
