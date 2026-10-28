select transaction_id
from {{ source('enrichment', 'transaction_categorizations') }}
where status = 'active'
group by transaction_id
having count(*) > 1
