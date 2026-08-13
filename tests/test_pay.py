"""Pay arithmetic: exact totals, single terminal rounding, transparent receipt (AC4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from lib.errors import TimesheetError
from lib.pay import build_receipt, sum_hours, total_from_days

# --------------------------------------------------------------------------
# exact totals — never float
# --------------------------------------------------------------------------


def test_sum_is_exact_where_float_would_drift() -> None:
    # 0.1 * 10 is 0.9999999999999999 in binary floating point.
    assert sum_hours(["0.1"] * 10) == Decimal("1.0")
    assert sum_hours(["7.5", "7.5", "0.25"]) == Decimal("15.25")


def test_sum_accepts_german_decimal_comma() -> None:
    assert sum_hours(["7,5", "0,25"]) == Decimal("7.75")


def test_empty_and_missing_values_contribute_nothing() -> None:
    assert sum_hours([]) == Decimal("0")
    assert sum_hours([None, "8", None]) == Decimal("8")


def test_total_from_days_ignores_days_without_hours() -> None:
    days = [
        {"date": "2026-08-03", "value": "7.5"},
        {"date": "2026-08-04", "value": None},  # unreadable or blank
        {"date": "2026-08-05", "value": "0"},
        {"date": "2026-08-06", "value": "8.25"},
    ]
    assert total_from_days(days) == Decimal("15.75")


def test_total_rejects_a_float_that_slipped_into_a_day() -> None:
    with pytest.raises(TimesheetError) as excinfo:
        total_from_days([{"date": "2026-08-03", "value": 7.5}])
    assert excinfo.value.code == "invalid_hours"


def test_leap_february_total_is_exact() -> None:
    """29 working days at 8.5 h — AC6's leap-year arithmetic case."""
    assert sum_hours(["8.5"] * 29) == Decimal("246.5")


# --------------------------------------------------------------------------
# rounding boundary — kaufmaennisches Runden, applied exactly once
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hours", "rate", "expected_exact", "expected_gross"),
    [
        # half a cent rounds UP (banker's rounding would give 3.50)
        ("0.5", "7.01", "3.505", "3.51"),
        ("1.5", "8.005", "12.0075", "12.01"),
        # a third of a cent rounds down
        ("0.25", "7.013", "1.75325", "1.75"),
        # exact to the cent — nothing to round
        ("60.0", "7.50", "450.000", "450.00"),
        ("76.5", "7.55", "577.575", "577.58"),
    ],
)
def test_gross_pay_rounds_half_up_once(hours, rate, expected_exact, expected_gross) -> None:
    receipt = build_receipt(Decimal(hours), rate, "CHF")
    assert receipt["exact_amount"] == expected_exact
    assert receipt["gross_pay"] == expected_gross


def test_rounding_is_terminal_not_per_day() -> None:
    """Three days of 0.005-worth of rounding must not become three cents."""
    per_day = Decimal("0.5")
    rate = "7.01"
    total = per_day * 3
    assert build_receipt(total, rate, "CHF")["gross_pay"] == "10.52"  # 10.515 -> 10.52
    # Rounding each day first and summing would give 3 * 3.51 = 10.53.


# --------------------------------------------------------------------------
# receipt transparency
# --------------------------------------------------------------------------


def test_receipt_shows_the_unrounded_product_when_rounding_changed_it() -> None:
    receipt = build_receipt(Decimal("0.5"), "7.01", "CHF")
    assert receipt["rounding_applied"] is True
    assert receipt["exact_amount"] == "3.505"
    assert "3.505" in receipt["statement"]
    assert receipt["statement"].startswith("0.5 h x 7.01 CHF = 3.51 CHF")


def test_receipt_stays_quiet_when_nothing_was_rounded() -> None:
    receipt = build_receipt(Decimal("2"), "7.50", "CHF")
    assert receipt["rounding_applied"] is False
    assert receipt["statement"] == "2 h x 7.50 CHF = 15.00 CHF"


def test_receipt_preserves_the_registered_rate_scale_and_currency_label() -> None:
    receipt = build_receipt(Decimal("10"), "7.5000", "Swiss francs (gross)")
    assert receipt["hourly_rate"] == "7.5000"
    assert receipt["currency"] == "Swiss francs (gross)"
    assert receipt["gross_pay"] == "75.00"


def test_receipt_refuses_a_rate_that_is_not_decimal_text() -> None:
    with pytest.raises(TimesheetError) as excinfo:
        build_receipt(Decimal("10"), 7.5, "CHF")
    assert excinfo.value.code == "invalid_rate"
