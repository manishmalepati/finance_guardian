import base64
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.receipts.matching import Candidate, automatic_match, rank_candidates
from backend.receipts.parser import ReceiptParseError, parse_doordash, parse_receipt, parse_uber_eats


def message(body: str, sender: str = "DoorDash <orders@doordash.com>") -> dict:
    return {
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": "Your DoorDash order receipt"},
            ],
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")},
        },
    }


def uber_message(body: str, sender: str = "Uber Eats <noreply@uber.com>",
                 subject: str = "Your Market Kitchen order with Uber Eats") -> dict:
    sample = message(body, sender)
    sample["payload"]["headers"][1]["value"] = subject
    return sample


RECEIPT = """Order #DEMO-12345
Order placed: 2026-10-12 19:30:00-07:00
1 x Veggie Bowl USD $14.00
2 x Sparkling Water USD $6.00
Subtotal USD $20.00
Delivery fee USD $2.00
Tax USD $1.50
Tip USD $3.50
Total USD $27.00
"""


def candidate(id_: str, amount: str = "27.00", merchant: str = "DOORDASH", status: str = "active") -> Candidate:
    return Candidate(id_, Decimal(amount), "USD", merchant, date(2026, 10, 12), date(2026, 10, 13), "debit", status)


def test_receipt_extracts_items_charges_and_order_identity():
    parsed = parse_doordash(message(RECEIPT))
    assert parsed.merchant_order_id == "DEMO-12345"
    assert parsed.placed_date == date(2026, 10, 12)
    assert parsed.currency == "USD"
    assert parsed.total == Decimal("27.00")
    assert parsed.tip == Decimal("3.50")
    assert [(item.description, item.quantity, item.line_total) for item in parsed.items] == [
        ("Veggie Bowl", Decimal("1"), Decimal("14.00")),
        ("Sparkling Water", Decimal("2"), Decimal("6.00")),
    ]
    assert parsed.parse_quality == "complete"


def test_invalid_receipt_fails_without_invented_order():
    with pytest.raises(ReceiptParseError, match="no_order_data"):
        parse_doordash(message("Thanks for your order."))
    with pytest.raises(ReceiptParseError, match="unsupported_sender"):
        parse_doordash(message(RECEIPT, sender="stranger@example.com"))


def test_html_receipt_keeps_labels_and_amounts_together():
    html = "<div>Order placed: 2026-10-12</div><div>1 x Veggie Bowl <span>USD $14.00</span></div><div>Total <span>USD $14.00</span></div>"
    sample = message("")
    sample["payload"]["mimeType"] = "text/html"
    sample["payload"]["body"]["data"] = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
    parsed = parse_doordash(sample)
    assert parsed.total == Decimal("14.00")
    assert parsed.items[0].description == "Veggie Bowl"


def test_uber_eats_total_only_email_preserves_unknown_items_and_currency():
    parsed = parse_receipt(uber_message("Oct 14, 2026\nYour receipt\nTotal $19.50\nOrder details"))
    assert parsed.merchant == "Uber Eats"
    assert parsed.placed_date == date(2026, 10, 14)
    assert parsed.total == Decimal("19.50")
    assert parsed.items == []
    assert parsed.currency is None
    assert parsed.parse_quality == "partial"


def test_uber_eats_html_receipt_extracts_separated_total_markup():
    sample = uber_message("")
    sample["payload"]["mimeType"] = "text/html"
    sample["payload"]["body"]["data"] = base64.urlsafe_b64encode(
        b"<div>Oct 14, 2026</div><div>Total <span>$19.50</span></div>"
    ).decode().rstrip("=")
    parsed = parse_receipt(sample)
    assert parsed.total == Decimal("19.50")
    assert parsed.placed_date == date(2026, 10, 14)


def test_uber_eats_itemized_fixture_and_strict_sender_subject():
    body = "Oct 14, 2026\n1 x Noodle Bowl USD $12.00\n1 x Iced Tea USD $3.00\nTotal USD $19.50"
    parsed = parse_uber_eats(uber_message(body))
    assert parsed.currency == "USD"
    assert parsed.parse_quality == "complete"
    assert len(parsed.items) == 2
    with pytest.raises(ReceiptParseError, match="unsupported_sender"):
        parse_receipt(uber_message(body, sender="Unknown <fake@example.com>"))
    with pytest.raises(ReceiptParseError, match="unsupported_subject"):
        parse_uber_eats(uber_message(body, subject="Save on Uber Eats today"))
    with pytest.raises(ReceiptParseError, match="missing_or_ambiguous_total"):
        parse_uber_eats(uber_message("Oct 14, 2026\nOrder details"))


def test_matching_requires_unique_strong_evidence():
    order = parse_doordash(message(RECEIPT))
    assert automatic_match(order, [candidate("one")]).transaction_id == "one"
    assert automatic_match(order, [candidate("one"), candidate("two")]) is None
    assert automatic_match(order, [candidate("one", amount="25.00")]) is None
    assert automatic_match(order, [candidate("one", status="superseded")]) is None
    later_charge = Candidate("later", Decimal("27.00"), "USD", "DoorDash",
                             date(2026, 10, 15), date(2026, 10, 15), "debit", "active")
    assert rank_candidates(order, [later_charge])
    assert automatic_match(order, [later_charge]) is None


def test_missing_currency_or_date_does_not_auto_confirm():
    order = SimpleNamespace(
        currency=None, total=Decimal("27.00"), merchant="DoorDash",
        placed_date=date(2026, 10, 12), placed_at=None,
    )
    assert rank_candidates(order, [candidate("one")])[0].confidence == Decimal("0.900")
    assert automatic_match(order, [candidate("one")]) is None
    order.currency = "USD"
    order.placed_date = None
    assert automatic_match(order, [candidate("one")]) is None


def test_refund_and_superseded_charge_are_never_candidates():
    order = parse_doordash(message(RECEIPT))
    refund = Candidate("refund", Decimal("27.00"), "USD", "DoorDash", date(2026, 10, 12), date(2026, 10, 13), "credit", "active")
    old_pending = candidate("pending", status="superseded")
    assert rank_candidates(order, [refund, old_pending]) == []


def test_split_charges_and_combined_orders_need_manual_review():
    order = parse_doordash(message(RECEIPT))
    assert automatic_match(order, [candidate("first", amount="14.00"), candidate("second", amount="13.00")]) is None
    first_order = SimpleNamespace(currency="USD", total=Decimal("10.00"), merchant="DoorDash", placed_date=date(2026, 10, 12), placed_at=None)
    second_order = SimpleNamespace(currency="USD", total=Decimal("17.00"), merchant="DoorDash", placed_date=date(2026, 10, 12), placed_at=None)
    combined_charge = [candidate("combined", amount="27.00")]
    assert automatic_match(first_order, combined_charge) is None
    assert automatic_match(second_order, combined_charge) is None
