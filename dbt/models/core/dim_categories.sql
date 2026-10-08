select distinct
    category_id,
    category
from {{ ref('stg_chase_transactions') }}
