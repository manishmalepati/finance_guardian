with active_categorizations as (
    select
        transaction_id,
        normalized_merchant,
        canonical_merchant_name,
        category_id,
        source as categorization_source,
        confidence as categorization_confidence
    from {{ source('enrichment', 'transaction_categorizations') }}
    where status = 'active'
)

select
    t.id as transaction_id,
    t.statement_import_id,
    t.posted_date,
    trim(t.description) as description,
    t.amount,
    t.direction,
    t.account_name,
    coalesce(c.category_id, 'other_uncategorized') as category_id,
    coalesce(ct.display_name, 'Uncategorized') as subcategory,
    coalesce(parent_ct.category_id, 'other') as parent_category_id,
    coalesce(parent_ct.display_name, 'Other') as parent_category,
    c.normalized_merchant,
    coalesce(c.canonical_merchant_name, trim(t.description)) as merchant_name,
    c.categorization_source,
    c.categorization_confidence,
    t.source,
    t.page_number,
    t.row_number,
    t.created_at
from {{ source('raw', 'statement_transactions') }} t
left join active_categorizations c on c.transaction_id = t.id
left join {{ source('enrichment', 'category_taxonomy') }} ct on ct.category_id = c.category_id
left join {{ source('enrichment', 'category_taxonomy') }} parent_ct on parent_ct.category_id = ct.parent_category_id
where t.source = 'chase_pdf'
