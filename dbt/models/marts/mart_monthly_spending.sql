select
    date_trunc('month', posted_date)::date as month,
    sum(case when direction = 'debit' then amount else 0 end) as debits,
    sum(case when direction = 'credit' then amount else 0 end) as credits,
    sum(signed_amount) as net_spend,
    sum(case when direction = 'debit' and not is_pending then amount else 0 end) as posted_debits,
    sum(case when direction = 'credit' and not is_pending then amount else 0 end) as posted_credits,
    sum(case when not is_pending then signed_amount else 0 end) as posted_net_spend,
    sum(case when direction = 'debit' and is_pending then amount else 0 end) as pending_debits,
    sum(case when direction = 'credit' and is_pending then amount else 0 end) as pending_credits,
    sum(case when is_pending then signed_amount else 0 end) as pending_net_spend,
    count(*) as transaction_count,
    sum(case when not is_pending then 1 else 0 end) as posted_transaction_count,
    sum(case when is_pending then 1 else 0 end) as pending_transaction_count
from {{ ref('fct_transactions') }}
where category_id not in ('financial_transfers', 'financial_credit_card_payment')
group by 1
