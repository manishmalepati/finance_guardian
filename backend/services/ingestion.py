import hashlib

from sqlalchemy.orm import Session

from backend.db.models import RawTransaction, StatementImport
from backend.ingestion.adapters.factory import AdapterFactory
from backend.repositories.transactions import TransactionRepository


class IngestionService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = TransactionRepository(session)
        self.adapter_factory = AdapterFactory()

    def import_statement(self, filename: str, content: bytes, source: str = "chase_pdf") -> dict:
        file_hash = hashlib.sha256(content).hexdigest()
        existing = self.repository.find_import_by_hash(file_hash)
        if existing:
            return {
                "import_id": existing.id,
                "status": "duplicate",
                "transactions_imported": 0,
            }

        adapter = self.adapter_factory.for_source(source)
        parsed_transactions = adapter.parse(content)

        statement_import = StatementImport(source=source, filename=filename, file_hash=file_hash)
        self.session.add(statement_import)
        self.session.flush()

        for index, parsed in enumerate(parsed_transactions, start=1):
            source_key = f"{parsed.posted_date.isoformat()}|{parsed.description}|{parsed.amount}|{index}"
            self.session.add(
                RawTransaction(
                    statement_import_id=statement_import.id,
                    source=source,
                    source_transaction_key=source_key,
                    posted_date=parsed.posted_date,
                    description=parsed.description,
                    amount=parsed.amount,
                    direction=parsed.direction,
                    account_name=parsed.account_name,
                    category_hint=parsed.category_hint,
                    page_number=parsed.page_number,
                    row_number=parsed.row_number,
                )
            )

        self.session.commit()
        return {
            "import_id": statement_import.id,
            "status": "completed",
            "transactions_imported": len(parsed_transactions),
        }
