from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ParsedTransaction(BaseModel):
    posted_date: date
    description: str = Field(min_length=1)
    amount: Decimal
    direction: str
    account_name: str = "Chase"
    category_hint: str | None = None
    page_number: int | None = None
    row_number: int | None = None


class TransactionRead(BaseModel):
    id: str
    posted_date: date
    description: str
    amount: Decimal
    direction: str
    account_name: str
    category_hint: str | None = None
