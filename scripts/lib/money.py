"""Exact decimal arithmetic for hours and money.

Rules (spec R1/R7, implementation approach):

* ``Decimal`` is only ever constructed from a string that matched a strict
  finite grammar — never from a float, never from unvalidated input.
* Hours: ``^\\d{1,2}([.,]\\d{1,2})?$``. More precision is an error surfaced for
  correction, never silently rounded.
* Rate: ``^\\d{1,5}([.,]\\d{1,4})?$``.
* A German decimal comma is normalized to a dot; a single separator only
  (``7.5.5`` is rejected by the grammar).
* Exponent notation, ``NaN``, ``Infinity`` and signs are rejected by the same
  grammar — no special-casing needed, the pattern simply does not match them.
* Gross pay rounds ONCE, at the end, ROUND_HALF_UP to 0.01 (kaufmaennisches
  Runden). Nothing else in the codebase rounds money.
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from .errors import TimesheetError

HOURS_PATTERN = r"^\d{1,2}([.,]\d{1,2})?$"
RATE_PATTERN = r"^\d{1,5}([.,]\d{1,4})?$"

_HOURS_RE = re.compile(HOURS_PATTERN)
_RATE_RE = re.compile(RATE_PATTERN)

CENT = Decimal("0.01")


def _parse(raw: object, regex: re.Pattern[str], *, code: str, label: str, shape: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, str):
        raise TimesheetError(
            code,
            f"{label} must be given as text, for example \"{shape}\".",
            {"value": repr(raw)},
        )
    candidate = raw.strip()
    if regex.fullmatch(candidate) is None:
        raise TimesheetError(
            code,
            f"\"{raw}\" is not a valid {label.lower()}. Use digits with at most one "
            f"decimal separator (comma or dot), for example \"{shape}\".",
            {"value": raw, "pattern": regex.pattern},
        )
    return Decimal(candidate.replace(",", "."))


def parse_hours(raw: object) -> Decimal:
    """Parse an hours value (max 2 fraction digits) into an exact Decimal."""
    return _parse(raw, _HOURS_RE, code="invalid_hours", label="Hours value", shape="7.5")


def parse_rate(raw: object) -> Decimal:
    """Parse an hourly rate (max 4 fraction digits) into an exact Decimal."""
    return _parse(raw, _RATE_RE, code="invalid_rate", label="Hourly rate", shape="7.50")


def canonical_decimal_string(value: Decimal) -> str:
    """Dot-notation string that preserves the value's scale.

    ``Decimal("7.50")`` -> ``"7.50"``; never scientific notation, never
    quantized. This is the storage form of the hourly rate.
    """
    return format(value, "f")


def round_money(value: Decimal) -> Decimal:
    """Round to 0.01 with ROUND_HALF_UP (kaufmaennisches Runden)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def gross_pay(total_hours: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    """Return ``(exact_product, rounded_product)`` for a transparent receipt.

    The exact product is kept so the tally can show the unrounded number
    whenever rounding changed it.
    """
    exact = total_hours * rate
    return exact, round_money(exact)


def format_money(value: Decimal) -> str:
    """Two-decimal display form of an already-rounded money amount."""
    return format(round_money(value), "f")
