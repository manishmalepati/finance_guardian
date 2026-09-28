select distinct
    md5(category) as category_id,
    category
from {{ ref('stg_chase_transactions') }}
