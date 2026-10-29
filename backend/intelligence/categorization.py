"""Provenance-aware examples; no ML package is loaded by the API."""

from dataclasses import dataclass
from datetime import date, datetime
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import CategorizationCorrection, Transaction


MODEL_VERSION = "tfidf_logreg_v1"


@dataclass(frozen=True)
class LabeledExample:
    transaction_id: str
    posted_date: date
    label_available_at: datetime
    description: str
    merchant: str
    category_id: str
    label_source: str
    plaid_hint: str | None = None


def clean_text(value: str) -> str:
    """Keep merchant words and remove noisy numbers without using the label."""
    value = re.sub(r"\b\d{2,}\b", " ", value.casefold())
    return " ".join(re.findall(r"[a-z]+", value))


def feature_text(example: LabeledExample) -> str:
    return clean_text(f"{example.merchant} {example.description}")


def explicit_local_examples(session: Session) -> list[LabeledExample]:
    """Use only independently selected transaction corrections, latest per ID.

    Existing `source=user` categorizations include alias propagation and are not
    independent ground truth. This function never writes a training dataset.
    """
    corrections = session.scalars(select(CategorizationCorrection).where(
        CategorizationCorrection.source == "user_explicit").order_by(
            CategorizationCorrection.transaction_id, CategorizationCorrection.created_at.desc(),
            CategorizationCorrection.id.desc())).all()
    latest = {}
    for correction in corrections:
        latest.setdefault(correction.transaction_id, correction)
    if not latest:
        return []
    transactions = {row.id: row for row in session.scalars(
        select(Transaction).where(Transaction.id.in_(latest))).all()}
    examples = []
    for transaction_id, correction in latest.items():
        transaction = transactions.get(transaction_id)
        if transaction is None or transaction.status != "active" or transaction.is_pending \
                or transaction.removed_at or transaction.replaced_by_transaction_id:
            continue
        examples.append(LabeledExample(
            transaction_id=str(transaction.id), posted_date=transaction.posted_date,
            label_available_at=correction.created_at,
            description=transaction.description, merchant=transaction.merchant_name or transaction.description,
            category_id=correction.category_id, label_source="user_explicit",
            plaid_hint=None))
    return sorted(examples, key=lambda item: (item.label_available_at, item.transaction_id))
