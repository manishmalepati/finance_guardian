select
    md5(date_trunc('month', t.posted_date)::date::text || ':' || t.account_id || ':' || c.category_id) as grain_key,
    date_trunc('month', t.posted_date)::date as month,
    t.account_id,
    c.parent_category_id,
    c.category_id,
    sum(case when not t.is_pending then t.amount else 0 end) as posted_amount,
    sum(case when t.is_pending then t.amount else 0 end) as pending_amount,
    count(*) as transaction_count
from {{ ref('fct_transactions') }} t
join {{ ref('dim_categories') }} c using (category_id)
where t.direction = 'debit'
  and c.category_id not in ('financial_transfers', 'financial_credit_card_payment')
  and t.account_id is not null
group by 2, 3, 4, 5
