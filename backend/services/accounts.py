import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import FinancialAccount, IngestionRun, PlaidItem, Transaction


class AccountService:
    def __init__(self, session: Session):
        self.session = session

    def list_accounts(self) -> list[dict]:
        rows = self.session.execute(
            select(FinancialAccount, PlaidItem.institution_name)
            .outerjoin(PlaidItem, FinancialAccount.plaid_item_id == PlaidItem.item_id)
            .order_by(FinancialAccount.name, FinancialAccount.id)
        ).all()
        return [
            {
                "id": account.id,
                "name": account.name,
                "mask": account.mask,
                "source": account.source,
                "account_type": account.account_type,
                "institution_name": institution_name if account.source == "plaid" else "Statement import",
                "iso_currency_code": account.iso_currency_code,
            }
            for account, institution_name in rows
        ]

    def statement_account(self, source: str, account_name: str) -> FinancialAccount:
        normalized = " ".join(account_name.casefold().split()) or "unknown account"
        source_key = hashlib.sha256(f"{source}:{normalized}".encode()).hexdigest()
        account = self.session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.source == "statement",
                FinancialAccount.source_account_key == source_key,
            )
        )
        if account is None:
            account = FinancialAccount(
                source="statement", source_account_key=source_key,
                name=account_name.strip() or "Unknown statement account",
            )
            self.session.add(account)
            self.session.flush()
        return account

    def link_legacy_statements(self) -> int:
        """Give older statement rows a stable statement-only account identity."""
        rows = self.session.execute(
            select(Transaction, IngestionRun.source)
            .join(IngestionRun, Transaction.ingestion_run_id == IngestionRun.id)
            .where(Transaction.source == "statement", Transaction.account_id.is_(None))
        ).all()
        for transaction, source in rows:
            transaction.account_id = self.statement_account(source, transaction.account_name).id
        if rows:
            self.session.commit()
        return len(rows)
