from sqlalchemy.orm import Session

from backend.repositories.transactions import TransactionRepository
from backend.services.analytics import AnalyticsService


class FinanceTools:
    def __init__(self, session: Session):
        self.session = session
        self.analytics = AnalyticsService(session)
        self.transactions = TransactionRepository(session)

    def get_monthly_summary(self) -> list[dict]:
        return self.analytics.monthly_summary()

    def get_spending_by_category(self) -> list[dict]:
        return self.analytics.category_spending()

    def get_largest_transactions(self, limit: int = 10) -> list[dict]:
        return self.analytics.largest_transactions(limit=limit)

    def search_transactions(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.transactions.list_transactions(query=query, limit=limit)
        return [
            {
                "id": row.id,
                "posted_date": row.posted_date.isoformat(),
                "description": row.description,
                "amount": row.amount,
                "direction": row.direction,
            }
            for row in rows
        ]
