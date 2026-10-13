select
    c.parent_category,
    c.subcategory,
    date_trunc('month', t.posted_date)::date as month,
    sum(t.amount) as amount,
    sum(case when not t.is_pending then t.amount else 0 end) as posted_amount,
    sum(case when t.is_pending then t.amount else 0 end) as pending_amount,
    count(*) as transaction_count,
    sum(case when not t.is_pending then 1 else 0 end) as posted_transaction_count,
    sum(case when t.is_pending then 1 else 0 end) as pending_transaction_count
from {{ ref('fct_transactions') }} t
join {{ ref('dim_categories') }} c using (category_id)
where t.direction = 'debit'
group by 1, 2, 3
