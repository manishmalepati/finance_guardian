"""Read and correct receipt context without changing the bank ledger."""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Transaction
from backend.db.models import CategoryTaxonomy
from backend.receipts.models import EmailSource, Order, OrderItem, TransactionOrderMatch


def statuses(session: Session, transaction_ids: list[str]) -> dict[str, str]:
    if not transaction_ids:
        return {}
    rows = session.execute(select(
        TransactionOrderMatch.transaction_id, TransactionOrderMatch.status
    ).where(TransactionOrderMatch.transaction_id.in_(transaction_ids))).all()
    result = {id_: "no_receipt" for id_ in transaction_ids}
    for transaction_id, status in rows:
        if status == "confirmed":
            result[transaction_id] = "matched"
        elif status == "suggested" and result[transaction_id] != "matched":
            result[transaction_id] = "possible"
    return result


def transaction_context(session: Session, transaction_id: str) -> dict:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction was not found.")
    matches = session.scalars(select(TransactionOrderMatch).where(
        TransactionOrderMatch.transaction_id == transaction_id,
        TransactionOrderMatch.status.in_(("confirmed", "suggested")),
    ).order_by(TransactionOrderMatch.confidence.desc())).all()
    linked = []
    for match in matches:
        order = session.get(Order, match.order_id)
        if order is None:
            continue
        source = session.get(EmailSource, order.email_source_id)
        items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.position)).all()
        linked.append({
            "match_id": match.id, "status": match.status,
            "confidence": match.confidence, "reasons": match.reasons,
            "user_override": match.user_override,
            "order": {
                "id": order.id, "merchant": order.merchant,
                "merchant_order_id": order.merchant_order_id,
                "placed_date": order.placed_date, "placed_at": order.placed_at,
                "currency": order.currency, "subtotal": order.subtotal,
                "delivery_fee": order.delivery_fee, "tax": order.tax,
                "tip": order.tip, "other_fees": order.other_fees,
                "discount": order.discount, "total": order.total,
                "parse_quality": order.parse_quality,
                "items": [{
                    "id": item.id, "description": item.description,
                    "quantity": item.quantity, "unit_price": item.unit_price,
                    "line_total": item.line_total, "category_id": item.category_id,
                    "evidence": item.evidence,
                } for item in items],
                "source": {
                    "message_id": source.gmail_message_id,
                    "sender": source.sender, "subject": source.subject,
                    "received_at": source.received_at,
                    "parser_version": source.parser_version,
                } if source else None,
            },
        })
    return {
        "transaction": {
            "id": transaction.id, "merchant": transaction.merchant_name or transaction.description,
            "amount": transaction.amount, "currency": transaction.iso_currency_code,
            "direction": transaction.direction, "posted_date": transaction.posted_date,
            "authorized_date": transaction.authorized_date,
            "is_pending": transaction.is_pending, "status": transaction.status,
            "account_name": transaction.account_name,
        },
        "receipt_status": statuses(session, [transaction_id])[transaction_id],
        "matches": linked,
    }


def search_orders(session: Session, query: str, limit: int = 20) -> list[dict]:
    statement = select(Order).order_by(Order.placed_date.desc().nullslast()).limit(limit)
    if query:
        statement = statement.where(func.lower(Order.merchant).contains(query.lower()))
    orders = session.scalars(statement).all()
    return [{
        "id": order.id, "merchant": order.merchant,
        "placed_date": order.placed_date, "total": order.total,
        "currency": order.currency,
    } for order in orders]


def confirm_match(session: Session, transaction_id: str, order_id: str) -> dict:
    transaction = session.get(Transaction, transaction_id)
    order = session.get(Order, order_id)
    if transaction is None or order is None:
        raise HTTPException(status_code=404, detail="Transaction or order was not found.")
    if transaction.status not in {"active", "pending"} or transaction.direction != "debit":
        raise HTTPException(status_code=409, detail="Only an active debit can be linked to an order.")
    if order.currency and transaction.iso_currency_code and order.currency != transaction.iso_currency_code:
        raise HTTPException(status_code=409, detail="Order and transaction currencies differ.")
    match = session.scalar(select(TransactionOrderMatch).where(
        TransactionOrderMatch.transaction_id == transaction_id,
        TransactionOrderMatch.order_id == order_id,
    ))
    if match is None:
        match = TransactionOrderMatch(
            transaction_id=transaction_id, order_id=order_id,
            confidence=Decimal("1.000"), reasons=["user confirmed"],
        )
        session.add(match)
    match.status = "confirmed"
    match.user_override = True
    session.commit()
    return {"id": match.id, "status": match.status}


def unlink_match(session: Session, transaction_id: str, match_id: str) -> None:
    match = session.get(TransactionOrderMatch, match_id)
    if match is None or match.transaction_id != transaction_id:
        raise HTTPException(status_code=404, detail="Match was not found.")
    match.status = "rejected"
    match.user_override = True
    session.commit()


def correct_item(session: Session, item_id: str, description: str | None, category_id: str | None) -> dict:
    item = session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Order item was not found.")
    if description is not None:
        item.description = description
    if category_id is not None:
        if category_id:
            category = session.get(CategoryTaxonomy, category_id)
            if category is None or not category.is_active:
                raise HTTPException(status_code=400, detail="Choose an active item category.")
        item.category_id = category_id or None
    session.commit()
    return {"id": item.id, "description": item.description, "category_id": item.category_id}
