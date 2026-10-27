"""Targeted Gmail import with idempotent, per-message recovery."""

from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.common.exceptions import GmailIntegrationError
from backend.receipts.gmail_auth import GmailAuth
from backend.receipts.models import EmailSource, GmailConnection, GmailSyncRun, Order, OrderItem
from backend.receipts.parser import PARSER_VERSION, ReceiptParseError, headers, parse_receipt
from backend.receipts.reconciliation import ReceiptReconciler

GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
RECEIPT_QUERY = 'from:noreply@uber.com subject:"Uber Eats" newer_than:90d'


class GmailSync:
    def __init__(self, session: Session, client: httpx.Client | None = None):
        self.session = session
        self.client = client or httpx.Client(timeout=20)

    def _get(self, url: str, token: str, params: dict | None = None) -> dict:
        response = self.client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        response.raise_for_status()
        return response.json()

    def _message_ids(self, token: str) -> tuple[list[str], bool]:
        ids: list[str] = []
        page_token = None
        for _ in range(5):
            params = {"q": RECEIPT_QUERY, "maxResults": 100}
            if page_token:
                params["pageToken"] = page_token
            page = self._get(GMAIL_MESSAGES_URL, token, params)
            ids.extend(item["id"] for item in page.get("messages", []) if item.get("id"))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return list(dict.fromkeys(ids)), bool(page_token)

    def sync(self, connection: GmailConnection) -> dict:
        token = GmailAuth(self.session, self.client).access_token(connection)
        imported_links = 0
        run = GmailSyncRun(connection_id=connection.id, status="running")
        self.session.add(run)
        self.session.commit()
        try:
            message_ids, truncated = self._message_ids(token)
            run.discovered_count = len(message_ids)
            self.session.commit()
            for message_id in message_ids:
                existing = self.session.scalar(select(EmailSource).where(
                    EmailSource.connection_id == connection.id,
                    EmailSource.gmail_message_id == message_id,
                ))
                if existing and existing.parse_status in {"complete", "partial"}:
                    run.skipped_count += 1
                    self.session.commit()
                    continue
                try:
                    message = self._get(f"{GMAIL_MESSAGES_URL}/{message_id}", token, {"format": "full"})
                    parsed = parse_receipt(message)
                    with self.session.begin_nested():
                        match_result = self._persist(connection, message_id, message, parsed, existing)
                    run.imported_count += 1
                    imported_links += match_result["created"]
                    self.session.commit()
                except ReceiptParseError as exc:
                    self._record_failure(connection, message_id, existing, str(exc))
                    run.failed_count += 1
                    self.session.commit()
                except (httpx.HTTPError, ValueError, KeyError, SQLAlchemyError):
                    self.session.rollback()
                    run = self.session.get(GmailSyncRun, run.id)
                    existing = self.session.scalar(select(EmailSource).where(
                        EmailSource.connection_id == connection.id,
                        EmailSource.gmail_message_id == message_id,
                    ))
                    if existing and existing.parse_status in {"complete", "partial"}:
                        run.skipped_count += 1
                        self.session.commit()
                        continue
                    self._record_failure(connection, message_id, existing, "message_fetch_or_parse_error")
                    run.failed_count += 1
                    self.session.commit()
            try:
                reconciliation = ReceiptReconciler(self.session).reconcile_all()
                reconciliation["links_created"] += imported_links
                self.session.commit()
            except Exception:
                self.session.rollback()
                run = self.session.get(GmailSyncRun, run.id)
                connection = self.session.get(GmailConnection, connection.id)
                run.error_code = "receipt_reconciliation_error"
                reconciliation = {"status": "failed"}
            run.status = "limited" if truncated else "completed_with_errors" if run.failed_count or run.error_code else "completed"
            run.completed_at = datetime.now(UTC)
            connection.last_sync_at = run.completed_at
            self.session.commit()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            self.session.rollback()
            run = self.session.get(GmailSyncRun, run.id)
            run.status = "failed"
            run.error_code = "gmail_api_error"
            run.completed_at = datetime.now(UTC)
            self.session.commit()
            raise GmailIntegrationError("Gmail sync failed. The previous successful imports remain available.") from exc
        return {
            "status": run.status,
            "discovered": run.discovered_count,
            "imported": run.imported_count,
            "skipped": run.skipped_count,
            "failed": run.failed_count,
            "limited": truncated,
            "last_sync_at": run.completed_at,
            "reconciliation": reconciliation,
        }

    def _record_failure(self, connection: GmailConnection, message_id: str, existing: EmailSource | None, code: str) -> None:
        source = existing or EmailSource(
            connection_id=connection.id, gmail_message_id=message_id,
            parser_version=PARSER_VERSION, parse_status="failed",
        )
        source.parse_status = "failed"
        source.error_code = code[:100]
        if existing is None:
            self.session.add(source)

    def _persist(self, connection: GmailConnection, message_id: str, message: dict, parsed, existing: EmailSource | None) -> dict[str, int]:
        metadata = headers(message)
        received_at = None
        if message.get("internalDate"):
            try:
                received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000, UTC)
            except (ValueError, TypeError, OverflowError):
                pass
        source = existing or EmailSource(connection_id=connection.id, gmail_message_id=message_id)
        source.sender = metadata.get("from", "")[:500]
        source.subject = metadata.get("subject", "")[:500]
        source.received_at = received_at
        source.parser_version = PARSER_VERSION
        source.parse_status = parsed.parse_quality
        source.error_code = None
        if existing is None:
            self.session.add(source)
        self.session.flush()
        order = Order(
            email_source_id=source.id, order_index=0,
            merchant=parsed.merchant, merchant_order_id=parsed.merchant_order_id,
            placed_at=parsed.placed_at, placed_date=parsed.placed_date,
            currency=parsed.currency, subtotal=parsed.subtotal,
            delivery_fee=parsed.delivery_fee, tax=parsed.tax, tip=parsed.tip,
            other_fees=parsed.other_fees, discount=parsed.discount,
            total=parsed.total, parse_quality=parsed.parse_quality,
        )
        self.session.add(order)
        self.session.flush()
        for position, item in enumerate(parsed.items):
            self.session.add(OrderItem(
                order_id=order.id, position=position,
                description=item.description, quantity=item.quantity,
                line_total=item.line_total, evidence=item.evidence,
            ))
        return ReceiptReconciler(self.session).reconcile_order(order)
