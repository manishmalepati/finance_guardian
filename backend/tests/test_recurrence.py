from datetime import date, timedelta
from decimal import Decimal

from backend.services.recurrence import detect_candidates


AS_OF = date(2026, 10, 27)


def event(identifier, day, amount="12.00", merchant="Civic Internet", **changes):
    row = {
        "id": identifier, "account_id": "account-one", "posted_date": day,
        "amount": Decimal(amount), "direction": "debit", "status": "active",
        "is_pending": False, "removed_at": None, "replaced_by_transaction_id": None,
        "currency": "USD", "source": "plaid", "category_id": "housing_internet_phone",
        "merchant": merchant, "normalized_merchant": merchant.lower(),
    }
    row.update(changes)
    return row


def test_weekly_biweekly_and_monthly_candidates_have_evidence_and_next_date():
    rows = [
        *[event(f"weekly-{index}", date(2026, 10, 2) + timedelta(days=7 * index), "12.00", "Weekly Pass") for index in range(4)],
        *[event(f"biweekly-{index}", date(2026, 9, 12) + timedelta(days=14 * index), "40.00", "Biweekly Service") for index in range(4)],
        event("monthly-1", date(2026, 7, 31), "49.00", "Civic Internet"),
        event("monthly-2", date(2026, 8, 31), "49.00", "Civic Internet"),
        event("monthly-3", date(2026, 9, 30), "50.00", "Civic Internet"),
    ]
    result = detect_candidates(rows, AS_OF)
    by_name = {row["merchant"]: row for row in result["candidates"]}
    assert result["candidate_count"] == 3
    assert by_name["Weekly Pass"]["cadence"] == "weekly"
    assert by_name["Weekly Pass"]["confidence"] == "high"
    assert by_name["Weekly Pass"]["transaction_ids"] == [f"weekly-{index}" for index in range(4)]
    assert by_name["Biweekly Service"]["cadence"] == "biweekly"
    assert by_name["Civic Internet"]["cadence"] == "monthly"
    assert by_name["Civic Internet"]["next_expected_date"] == "2026-10-31"
    assert all(row["matching_intervals"] >= 2 for row in result["candidates"])


def test_calendar_month_end_and_leap_year_anchor():
    rows = [
        event("jan", date(2024, 1, 31)),
        event("feb", date(2024, 2, 29)),
        event("mar", date(2024, 3, 31)),
    ]
    candidate = detect_candidates(rows, date(2024, 4, 1))["candidates"][0]
    assert candidate["cadence"] == "monthly"
    assert candidate["next_expected_date"] == "2024-04-30"


def test_variable_groceries_irregular_purchases_and_stale_series_are_not_alerts():
    rows = [
        *[event(f"g-{index}", date(2026, 10, 3) + timedelta(days=7 * index), amount,
                "Grocery Basket") for index, amount in enumerate(("10.00", "60.00", "5.00"))],
        event("i1", date(2026, 9, 1), merchant="Irregular"),
        event("i2", date(2026, 9, 8), merchant="Irregular"),
        event("i3", date(2026, 10, 2), merchant="Irregular"),
        *[event(f"s-{index}", date(2026, 1, 1) + timedelta(days=7 * index),
                merchant="Old Series") for index in range(3)],
    ]
    assert detect_candidates(rows, AS_OF)["candidates"] == []


def test_pending_to_posted_movements_credits_missing_currency_and_exact_overlaps():
    rows = [
        event("a", date(2026, 10, 1)),
        event("b", date(2026, 10, 8)),
        event("c", date(2026, 10, 15)),
        event("pending", date(2026, 10, 14), status="removed", is_pending=True,
              replaced_by_transaction_id="c"),
        event("transfer", date(2026, 10, 22), category_id="financial_transfers"),
        event("refund", date(2026, 10, 22), direction="credit"),
        event("unknown", date(2026, 10, 22), currency=None),
        event("duplicate", date(2026, 10, 15), source="statement"),
    ]
    result = detect_candidates(rows, AS_OF)
    assert result["eligible_purchase_count"] == 3
    assert result["candidates"][0]["transaction_ids"] == ["a", "b", "c"]
    assert result["excluded_counts"] == {
        "not_settled_active": 1, "movements": 1, "credits": 1,
        "missing_currency": 1, "exact_statement_plaid_overlap": 1,
    }


def test_account_and_currency_are_separate_series_with_stable_keys():
    rows = [event(f"a{index}", date(2026, 10, 1) + timedelta(days=7 * index)) for index in range(3)]
    rows += [event(f"b{index}", date(2026, 10, 1) + timedelta(days=7 * index),
                   account_id="account-two") for index in range(3)]
    rows += [event(f"e{index}", date(2026, 10, 1) + timedelta(days=7 * index),
                   currency="EUR") for index in range(3)]
    first = detect_candidates(rows, AS_OF)
    second = detect_candidates(list(reversed(rows)), AS_OF)
    assert len({item["series_key"] for item in first["candidates"]}) == 3
    assert {item["series_key"] for item in first["candidates"]} == {
        item["series_key"] for item in second["candidates"]
    }


def test_annual_cadence_requires_three_observations():
    rows = [event(str(year), date(year, 10, 1), "100.00", "Annual Plan") for year in (2024, 2025, 2026)]
    result = detect_candidates(rows, AS_OF)
    assert result["candidates"][0]["cadence"] == "yearly"
    assert result["candidates"][0]["next_expected_date"] == "2027-10-01"


def test_latest_charge_increase_is_observed_not_a_future_price_claim():
    rows = [
        event("first", date(2026, 8, 5), "10.00"),
        event("second", date(2026, 9, 5), "10.00"),
        event("third", date(2026, 10, 5), "13.00"),
    ]
    candidate = detect_candidates(rows, AS_OF)["candidates"][0]
    assert candidate["latest_increase_vs_previous"] == "3.00"
    assert candidate["observed_high"] == "13.00"
