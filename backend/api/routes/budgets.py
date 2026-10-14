from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import CategoryTaxonomy, MonthlyCategoryLimit
from backend.db.session import get_session

router = APIRouter()


class MonthlyLimitInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


@router.get("/monthly-limits")
def list_monthly_limits(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(MonthlyCategoryLimit).order_by(MonthlyCategoryLimit.category_id)).all()
    return [{"category_id": row.category_id, "amount": row.amount} for row in rows]


@router.put("/monthly-limits/{category_id}")
def set_monthly_limit(
    category_id: str, payload: MonthlyLimitInput, session: Session = Depends(get_session)
) -> dict:
    category = session.get(CategoryTaxonomy, category_id)
    if not category or category.parent_category_id is not None or category_id in {"income", "other"} or not category.is_active:
        raise HTTPException(status_code=400, detail="Choose an active spending category.")

    row = session.get(MonthlyCategoryLimit, category_id)
    if row is None:
        row = MonthlyCategoryLimit(category_id=category_id, amount=payload.amount)
        session.add(row)
    else:
        row.amount = payload.amount
    session.commit()
    return {"category_id": row.category_id, "amount": row.amount}


@router.delete("/monthly-limits/{category_id}", status_code=204)
def delete_monthly_limit(category_id: str, session: Session = Depends(get_session)) -> None:
    row = session.get(MonthlyCategoryLimit, category_id)
    if row is not None:
        session.delete(row)
        session.commit()
