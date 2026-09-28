select
    date_trunc('month', posted_date)::date as month,
    sum(case when direction = 'debit' then amount else 0 end) as debits,
    sum(case when direction = 'credit' then amount else 0 end) as credits,
    sum(signed_amount) as net_spend,
    count(*) as transaction_count
from {{ ref('fct_transactions') }}
group by 1
