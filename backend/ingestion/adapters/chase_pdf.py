import re
from io import BytesIO
from datetime import date
from decimal import Decimal

import pdfplumber

from backend.domain.transactions import ParsedTransaction
from backend.ingestion.adapters.base import StatementAdapter


class ChasePdfAdapter(StatementAdapter):
    source = "chase_pdf"
    _transaction_line = re.compile(
        r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+(?P<description>.+?)\s+(?P<amount>-?\$?\d[\d,]*\.\d{2})$"
    )

    def parse(self, content: bytes) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                for row_index, raw_line in enumerate(text.splitlines(), start=1):
                    parsed = self._parse_line(raw_line, page_index, row_index)
                    if parsed:
                        transactions.append(parsed)
        return transactions

    def _parse_line(self, line: str, page_number: int, row_number: int) -> ParsedTransaction | None:
        match = self._transaction_line.match(" ".join(line.split()))
        if not match:
            return None

        # Chase statement rows generally omit the year in transaction tables.
        # MVP uses current year until statement-period detection is added.
        posted_date = date.today().replace(month=int(match["month"]), day=int(match["day"]))
        amount = Decimal(match["amount"].replace("$", "").replace(",", ""))
        direction = "credit" if amount < 0 else "debit"

        return ParsedTransaction(
            posted_date=posted_date,
            description=match["description"].strip(),
            amount=abs(amount),
            direction=direction,
            page_number=page_number,
            row_number=row_number,
        )
