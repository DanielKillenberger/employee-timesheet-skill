"""Pay arithmetic: exact hour totals and a transparent gross-pay receipt (R3/R5, AC4).

Two rules, both load-bearing:

* **The total is exact.** Daily hours are summed as ``Decimal`` values parsed
  from strings — never floats — and the sum is never rounded. ``7.5 + 7.5 +
  0.25`` is ``15.25``, not ``15.249999999999998``.
* **Money rounds exactly once, at the end.** ``gross = total x rate`` is
  computed at full precision and then quantized to 0.01 with ROUND_HALF_UP
  (kaufmaennisches Runden) by :func:`lib.money.gross_pay`. No intermediate
  value is ever rounded, so no rounding error can compound.

The receipt keeps the unrounded product whenever rounding changed the number,
so the final amount is auditable by hand: the tally document (task .4) prints
exactly what this module returns.

This module is pure — no I/O, no registry access, no session knowledge.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from .money import canonical_decimal_string, gross_pay, parse_hours, parse_rate

ZERO = Decimal("0")


def sum_hours(values: Iterable[object]) -> Decimal:
    """Exact sum of hour values given as strings (or ``None`` for "no hours")."""
    total = ZERO
    for value in values:
        if value is None:
            continue
        total += parse_hours(value)
    return total


def total_from_days(days: Iterable[Mapping[str, Any]]) -> Decimal:
    """Exact sum over day records, ignoring days that carry no hours.

    A day contributes only when it has a ``value``; ``blank``, ``zero`` without
    a value, and ``unreadable`` days contribute nothing. Note that this is the
    *provisional* rule as well as the confirmed one — the difference is not in
    the arithmetic but in whether unreadable days are still allowed to exist
    (they are, provisionally; :mod:`lib.extraction` refuses to confirm them).
    """
    return sum_hours(day.get("value") for day in days)


def build_receipt(total_hours: Decimal, rate: object, currency: str) -> dict[str, Any]:
    """Return the transparent ``hours x rate = gross`` receipt (AC4).

    ``rate`` is accepted as the canonical string stored in the registry (or a
    ``Decimal``); it is re-parsed through the money grammar so a hand-edited
    registry cannot smuggle a float or an exponent into payroll arithmetic.
    """
    rate_decimal = rate if isinstance(rate, Decimal) else parse_rate(rate)
    exact, rounded = gross_pay(total_hours, rate_decimal)
    rounding_applied = exact != rounded

    total_text = canonical_decimal_string(total_hours)
    rate_text = canonical_decimal_string(rate_decimal)
    gross_text = canonical_decimal_string(rounded)
    exact_text = canonical_decimal_string(exact)

    statement = f"{total_text} h x {rate_text} {currency} = {gross_text} {currency}"
    if rounding_applied:
        statement += f" (exact {exact_text} {currency}, rounded to the nearest 0.01)"

    return {
        "total_hours": total_text,
        "hourly_rate": rate_text,
        "currency": currency,
        "gross_pay": gross_text,
        "exact_amount": exact_text,
        "rounding_applied": rounding_applied,
        "statement": statement,
    }
