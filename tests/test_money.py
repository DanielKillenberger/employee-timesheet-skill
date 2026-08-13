"""Grammar and rounding rules for hours and money."""

from __future__ import annotations

from decimal import Decimal

import pytest

from lib.errors import TimesheetError
from lib.money import (
    canonical_decimal_string,
    format_money,
    gross_pay,
    parse_hours,
    parse_rate,
    round_money,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7", "7"), ("7.5", "7.5"), ("7,5", "7.5"), ("0,25", "0.25"), ("24", "24"), ("00.5", "0.5")],
)
def test_parse_hours_accepts_dot_and_comma(raw: str, expected: str) -> None:
    assert canonical_decimal_string(parse_hours(raw)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "7.555",  # excess precision is an error, never silently rounded
        "7.5.5",  # more than one separator
        "1e2",  # exponent notation
        "NaN",
        "Infinity",
        "-1",
        "+1",
        "7.",
        ".5",
        "",
        "  ",
        "abc",
        "7 5",
        "247",  # more than two integer digits
    ],
)
def test_parse_hours_rejects_bad_shapes(raw: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        parse_hours(raw)
    assert excinfo.value.code == "invalid_hours"


@pytest.mark.parametrize("raw", [7.5, 7, None, True, ["7"]])
def test_parse_hours_rejects_non_strings(raw: object) -> None:
    """Decimal is never constructed from a float (or anything but text)."""
    with pytest.raises(TimesheetError):
        parse_hours(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7,50", "7.50"), ("7.5", "7.5"), ("12", "12"), ("99999.1234", "99999.1234"), ("0,0001", "0.0001")],
)
def test_parse_rate_preserves_scale(raw: str, expected: str) -> None:
    assert canonical_decimal_string(parse_rate(raw)) == expected


@pytest.mark.parametrize("raw", ["7.50000", "123456", "-7.50", "7,5,0", "1E3", "NaN", "inf"])
def test_parse_rate_rejects_bad_shapes(raw: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        parse_rate(raw)
    assert excinfo.value.code == "invalid_rate"


def test_canonical_string_never_uses_scientific_notation() -> None:
    assert canonical_decimal_string(parse_rate("0,0001")) == "0.0001"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.025", "0.03"),  # exact half cent rounds up (banker's rounding would give 0.02)
        ("1.725", "1.73"),  # ditto (banker's rounding would give 1.72)
        ("1.005", "1.01"),
        ("2.344", "2.34"),
        ("2.345", "2.35"),
        ("0.004", "0.00"),
    ],
)
def test_round_money_is_half_up(raw: str, expected: str) -> None:
    assert canonical_decimal_string(round_money(Decimal(raw))) == expected


def test_gross_pay_rounds_once_at_the_end() -> None:
    hours = parse_hours("0,5")
    rate = parse_rate("0,05")
    exact, rounded = gross_pay(hours, rate)
    assert exact == Decimal("0.025")
    assert rounded == Decimal("0.03")


def test_gross_pay_sum_then_multiply_is_exact() -> None:
    """Per-day rounding would drift; only the final product is rounded."""
    daily = [parse_hours("7,33") for _ in range(3)]
    total = sum(daily, Decimal("0"))
    rate = parse_rate("21,25")
    exact, rounded = gross_pay(total, rate)
    assert total == Decimal("21.99")
    assert exact == Decimal("467.2875")
    assert rounded == Decimal("467.29")
    assert format_money(rounded) == "467.29"
