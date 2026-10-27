from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.goals.service import GoalError, GoalService

router = APIRouter()


class MonthlyLimitInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


@router.get("/monthly-limits")
def list_monthly_limits(session: Session = Depends(get_session)) -> list[dict]:
    return [
        {"category_id": goal["category_id"], "amount": goal["threshold_amount"]}
        for goal in GoalService(session).list()
        if goal["metric_type"] == "monthly_spend" and goal["status"] == "active"
    ]


@router.put("/monthly-limits/{category_id}")
def set_monthly_limit(
    category_id: str, payload: MonthlyLimitInput, session: Session = Depends(get_session)
) -> dict:
    service = GoalService(session)
    try:
        service.validate_scope(category_id)
        goal = service.find_monthly_scope(category_id)
        if goal is None:
            result = service.create(category_id=category_id, threshold_amount=payload.amount, timezone="UTC")
        else:
            result = service.update(goal.id, {"threshold_amount": payload.amount, "status": "active"})
        return {"category_id": result["category_id"], "amount": result["threshold_amount"]}
    except GoalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/monthly-limits/{category_id}", status_code=204)
def delete_monthly_limit(category_id: str, session: Session = Depends(get_session)) -> None:
    service = GoalService(session)
    goal = service.find_monthly_scope(category_id)
    if goal is not None:
        service.delete(goal.id)
