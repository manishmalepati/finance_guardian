import hashlib

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.common.exceptions import IngestionError
from backend.db.models import IngestionRun, StatementDocument, StatementRawTransaction, Transaction
from backend.ingestion.adapters.factory import AdapterFactory
from backend.repositories.transactions import TransactionRepository
from backend.services.categorization import CategorizationService


class IngestionService:
    """Coordinates statement parsing, idempotency checks, and canonical fallback persistence."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = TransactionRepository(session)
        self.adapter_factory = AdapterFactory()

    def import_statement(self, filename: str, content: bytes, source: str = "chase_pdf") -> dict:
        """Import one statement file if its content hash has not been seen."""

        file_hash = hashlib.sha256(content).hexdigest()
        existing = self.repository.find_ingestion_run_by_fingerprint(file_hash)
        if existing:
            return {
                "import_id": existing.id,
                "status": "duplicate",
                "transactions_imported": 0,
            }

        try:
            adapter = self.adapter_factory.for_source(source)
            parsed_transactions = adapter.parse(content)

            ingestion_run = IngestionRun(source=source, filename=filename, source_fingerprint=file_hash)
            self.session.add(ingestion_run)
            self.session.flush()
            statement_document = StatementDocument(
                ingestion_run_id=ingestion_run.id,
                source=source,
                filename=filename,
                file_hash=file_hash,
            )
            self.session.add(statement_document)
            self.session.flush()

            for index, parsed in enumerate(parsed_transactions, start=1):
                source_key = self._statement_row_hash(file_hash=file_hash, row_number=index, parsed=parsed)
                canonical_transaction = Transaction(
                    ingestion_run_id=ingestion_run.id,
                    source="statement",
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
                self.session.add(canonical_transaction)
                self.session.flush()
                self.session.add(
                    StatementRawTransaction(
                        statement_document_id=statement_document.id,
                        canonical_transaction_id=canonical_transaction.id,
                        statement_row_hash=source_key,
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
            self.session.flush()
            categorization_result = CategorizationService(self.session).apply_known_aliases_and_queue_unknowns(commit=False)
            self.session.commit()
        except IngestionError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise IngestionError("Statement import failed while saving transactions.") from exc
        except Exception as exc:
            self.session.rollback()
            raise IngestionError("Statement import failed while parsing the statement.") from exc

        return {
            "import_id": ingestion_run.id,
            "status": "completed",
            "transactions_imported": len(parsed_transactions),
            "transactions_categorized": categorization_result["transactions_categorized"],
            "unknown_merchants_queued": categorization_result["unknown_merchants_queued"],
        }

    def _statement_row_hash(self, file_hash: str, row_number: int, parsed) -> str:
        stable_parts = [
            file_hash,
            str(row_number),
            parsed.posted_date.isoformat(),
            parsed.description.strip().lower(),
            str(parsed.amount),
            parsed.direction,
        ]
        return hashlib.sha256("|".join(stable_parts).encode("utf-8")).hexdigest()
