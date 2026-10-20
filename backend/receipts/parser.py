"""Narrow, deterministic parsing of supported purchase receipt messages."""

import base64
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr
from html.parser import HTMLParser

PARSER_VERSION = "merchant-v2"
_MONEY = r"(?:USD\s*)?\$\s*([\d,]+\.\d{2})"
_ITEM = re.compile(r"^(?P<quantity>\d+(?:\.\d+)?)\s*[x×]\s+(?P<description>.+?)\s+(?:USD\s*)?\$(?P<total>[\d,]+\.\d{2})$", re.I)
_ORDER_ID = re.compile(r"(?:order\s*(?:number|#|id)\s*[:#]?\s*)([A-Za-z0-9-]{4,})", re.I)
_ISO_DATE = re.compile(r"order\s+(?:placed|date)\s*:?\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?))?", re.I)


class ReceiptParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedItem:
    description: str
    quantity: Decimal | None
    line_total: Decimal | None
    evidence: str


@dataclass(frozen=True)
class ParsedOrder:
    merchant: str
    merchant_order_id: str | None = None
    placed_date: date | None = None
    placed_at: datetime | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    delivery_fee: Decimal | None = None
    tax: Decimal | None = None
    tip: Decimal | None = None
    other_fees: Decimal | None = None
    discount: Decimal | None = None
    total: Decimal | None = None
    items: list[ParsedItem] = field(default_factory=list)
    parse_quality: str = "partial"


class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.current: list[str] = []
        self.ignored_depth = 0

    def _flush(self) -> None:
        value = " ".join(self.current).strip()
        if value:
            self.lines.append(value)
        self.current = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        if tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth = max(0, self.ignored_depth - 1)
        if tag in {"tr", "p", "div", "li", "h1", "h2", "h3"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        value = " ".join(data.split())
        if value:
            self.current.append(value)

    def text(self) -> str:
        self._flush()
        return "\n".join(self.lines)


def _decode_body(part: dict) -> str:
    encoded = part.get("body", {}).get("data")
    if not encoded:
        return ""
    if len(encoded) > 200_000:
        raise ReceiptParseError("receipt_too_large")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        return raw.decode("utf-8", errors="replace")
    except (ValueError, TypeError) as exc:
        raise ReceiptParseError("invalid_receipt_encoding") from exc


def _parts(payload: dict):
    yield payload
    for part in payload.get("parts", []):
        yield from _parts(part)


def message_body(message: dict) -> str:
    payload = message.get("payload") or {}
    parts = list(_parts(payload))
    plain = next((_decode_body(part) for part in parts if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data")), "")
    if plain:
        return plain
    html = next((_decode_body(part) for part in parts if part.get("mimeType") == "text/html" and part.get("body", {}).get("data")), "")
    if html:
        parser = _TextHTML()
        parser.feed(html)
        return parser.text()
    raise ReceiptParseError("missing_receipt_body")


def headers(message: dict) -> dict[str, str]:
    return {str(row.get("name", "")).lower(): str(row.get("value", "")) for row in message.get("payload", {}).get("headers", [])}


def _money(line: str) -> Decimal | None:
    match = re.search(_MONEY, line, re.I)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def parse_doordash(message: dict) -> ParsedOrder:
    fields = headers(message)
    sender = parseaddr(fields.get("from", ""))[1].lower()
    if not sender.endswith("@doordash.com"):
        raise ReceiptParseError("unsupported_sender")
    subject = fields.get("subject", "")
    if not re.search(r"order|receipt", subject, re.I):
        raise ReceiptParseError("unsupported_subject")

    body = message_body(message)
    lines = [" ".join(line.split()) for line in body.splitlines()]
    lines = [line for line in lines if line]
    order_id_match = _ORDER_ID.search(body)
    date_match = _ISO_DATE.search(body)
    placed_date = None
    placed_at = None
    if date_match:
        try:
            placed_date = date.fromisoformat(date_match.group(1))
            if date_match.group(2):
                timestamp = datetime.fromisoformat(f"{date_match.group(1)}T{date_match.group(2).replace('Z', '+00:00')}")
                if timestamp.tzinfo is not None:
                    placed_at = timestamp
        except ValueError:
            pass

    amounts: dict[str, Decimal] = {}
    items: list[ParsedItem] = []
    labels = {
        "subtotal": r"^subtotal\b",
        "delivery_fee": r"^delivery\s+fee\b",
        "tax": r"^(?:tax|sales tax)\b",
        "tip": r"^(?:tip|dasher tip)\b",
        "other_fees": r"^(?:service fee|other fees)\b",
        "discount": r"^(?:discount|promotion|promo)\b",
        "total": r"^(?:order total|total charged|total)\b",
    }
    for line in lines:
        item_match = _ITEM.match(line)
        if item_match:
            items.append(ParsedItem(
                description=item_match.group("description")[:500],
                quantity=Decimal(item_match.group("quantity")),
                line_total=Decimal(item_match.group("total").replace(",", "")),
                evidence=line[:500],
            ))
            continue
        for key, pattern in labels.items():
            if re.search(pattern, line, re.I):
                amount = _money(line)
                if amount is not None:
                    amounts[key] = amount
                break

    if not items and "total" not in amounts:
        raise ReceiptParseError("no_order_data")
    explicit_usd = bool(re.search(r"\bUSD\b", body, re.I))
    return ParsedOrder(
        merchant="DoorDash",
        merchant_order_id=order_id_match.group(1) if order_id_match else None,
        placed_date=placed_date,
        placed_at=placed_at,
        currency="USD" if explicit_usd else None,
        items=items,
        parse_quality="complete" if items and "total" in amounts and placed_date and explicit_usd else "partial",
        **{key: amounts.get(key) for key in labels},
    )


def parse_uber_eats(message: dict) -> ParsedOrder:
    fields = headers(message)
    sender = parseaddr(fields.get("from", ""))[1].lower()
    if sender != "noreply@uber.com":
        raise ReceiptParseError("unsupported_sender")
    if not re.fullmatch(r"Your .+ order with Uber Eats\s*", fields.get("subject", ""), re.I):
        raise ReceiptParseError("unsupported_subject")

    body = message_body(message)
    lines = [" ".join(line.split()) for line in body.splitlines() if line.strip()]
    placed_date = None
    for line in lines[:5]:
        if not re.fullmatch(r"[A-Za-z]+ \d{1,2}, \d{4}", line):
            continue
        for date_format in ("%b %d, %Y", "%B %d, %Y"):
            try:
                placed_date = datetime.strptime(line, date_format).date()
                break
            except ValueError:
                pass
        if placed_date:
            break

    total_lines = [match for line in lines if (match := re.fullmatch(
        rf"total\s+{_MONEY}", line, re.I
    ))]
    if len(total_lines) != 1:
        raise ReceiptParseError("missing_or_ambiguous_total")
    total = Decimal(total_lines[0].group(1).replace(",", ""))

    labels = {
        "subtotal": r"^subtotal\b",
        "delivery_fee": r"^delivery\s+fee\b",
        "tax": r"^(?:tax|sales tax|taxes)\b",
        "tip": r"^tip\b",
        "other_fees": r"^service fee\b",
        "discount": r"^(?:discount|promotion)\b",
    }
    amounts: dict[str, Decimal] = {}
    items: list[ParsedItem] = []
    for line in lines:
        item_match = _ITEM.match(line)
        if item_match:
            items.append(ParsedItem(
                description=item_match.group("description")[:500],
                quantity=Decimal(item_match.group("quantity")),
                line_total=Decimal(item_match.group("total").replace(",", "")),
                evidence=line[:500],
            ))
            continue
        for key, pattern in labels.items():
            if re.search(pattern, line, re.I):
                amount = _money(line)
                if amount is not None:
                    amounts[key] = amount
                break

    explicit_usd = bool(re.search(r"\bUSD\b", body, re.I))
    return ParsedOrder(
        merchant="Uber Eats", placed_date=placed_date,
        currency="USD" if explicit_usd else None,
        total=total, items=items,
        parse_quality="complete" if items and placed_date and explicit_usd else "partial",
        **{key: amounts.get(key) for key in labels},
    )


def parse_receipt(message: dict) -> ParsedOrder:
    sender = parseaddr(headers(message).get("from", ""))[1].lower()
    if sender == "noreply@uber.com":
        return parse_uber_eats(message)
    if sender.endswith("@doordash.com"):
        return parse_doordash(message)
    raise ReceiptParseError("unsupported_sender")
