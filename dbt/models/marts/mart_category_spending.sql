select
    c.category,
    date_trunc('month', t.posted_date)::date as month,
    sum(t.amount) as amount,
    count(*) as transaction_count
from {{ ref('fct_transactions') }} t
join {{ ref('dim_categories') }} c using (category_id)
where t.direction = 'debit'
group by 1, 2
