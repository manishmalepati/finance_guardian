select distinct
    category_id,
    subcategory,
    parent_category_id,
    parent_category
from {{ ref('stg_transactions') }}
