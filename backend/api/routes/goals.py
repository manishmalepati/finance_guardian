"""Monthly spending goals and evidence-backed evaluations."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.goals.service import GoalConflict, GoalError, GoalMissing, GoalService

router = APIRouter()


class GoalCreate(BaseModel):
    category_id: str = Field(min_length=1, max_length=50)
    threshold_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class GoalUpdate(BaseModel):
    category_id: str | None = Field(default=None, min_length=1, max_length=50)
    threshold_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["active", "paused"] | None = None


def _translate(exc: GoalError) -> HTTPException:
    status = 404 if isinstance(exc, GoalMissing) else 409 if isinstance(exc, GoalConflict) else 400
    return HTTPException(status_code=status, detail=str(exc))


@router.get("")
def list_goals(session: Session = Depends(get_session)) -> list[dict]:
    return GoalService(session).list()


@router.post("", status_code=201)
def create_goal(payload: GoalCreate, session: Session = Depends(get_session)) -> dict:
    try:
        return GoalService(session).create(**payload.model_dump())
    except GoalError as exc:
        raise _translate(exc) from exc


@router.get("/evaluations")
def evaluate_goals(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                   session: Session = Depends(get_session)) -> list[dict]:
    return GoalService(session).evaluate_all(month)


@router.get("/{goal_id}/evaluation")
def evaluate_goal(goal_id: UUID,
                  month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                  session: Session = Depends(get_session)) -> dict:
    try:
        service = GoalService(session)
        return service.evaluate(service.get(str(goal_id)), month)
    except GoalError as exc:
        raise _translate(exc) from exc


@router.patch("/{goal_id}")
def update_goal(goal_id: UUID, payload: GoalUpdate, session: Session = Depends(get_session)) -> dict:
    changes = {key: value for key, value in payload.model_dump(exclude_unset=True).items() if value is not None}
    try:
        return GoalService(session).update(str(goal_id), changes)
    except GoalError as exc:
        raise _translate(exc) from exc


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: UUID, session: Session = Depends(get_session)) -> None:
    try:
        GoalService(session).delete(str(goal_id))
    except GoalError as exc:
        raise _translate(exc) from exc
