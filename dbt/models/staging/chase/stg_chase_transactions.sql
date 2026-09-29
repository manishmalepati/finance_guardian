select
    id as transaction_id,
    statement_import_id,
    posted_date,
    trim(description) as description,
    amount,
    direction,
    account_name,
    coalesce(category_hint, 'Uncategorized') as category,
    source,
    page_number,
    row_number,
    created_at
from {{ source('raw', 'statement_transactions') }}
where source = 'chase_pdf'
