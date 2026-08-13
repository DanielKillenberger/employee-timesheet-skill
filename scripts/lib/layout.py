"""Month layout model — the single source of truth for what a monthly sheet shows.

This module is pure: it does no I/O, touches no files, and knows nothing about
XLSX or PDF. Given a worker record (see :mod:`lib.registry`) and a ``YYYY-MM``
month it returns one :class:`DayRow` per calendar date, in order, already
resolved into "working" or "off".

Both sheet renderers consume this model (openpyxl for XLSX, reportlab for PDF),
so the two documents can never disagree about dates, labels or grey rows.

Resolution rules (plan decision 3):

* the recurring weekday schedule decides by default;
* a month-specific ``off`` date makes the day off, whatever the schedule says;
* a month-specific ``extra`` date makes the day a working day;
* a date listed as both is rejected at registration, so it cannot arrive here.

Every label is German (spec R2). Keeping them in this one module is what makes
a later translation a small change rather than a rewrite.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .errors import TimesheetError

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_MONTH_RE = re.compile(MONTH_PATTERN)

#: Weekday keys, Monday first — the index matches ``datetime.date.weekday()``.
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: German weekday abbreviations, same order as :data:`WEEKDAYS`.
GERMAN_WEEKDAY_ABBREVIATIONS: tuple[str, ...] = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

#: German month names, index 1..12.
GERMAN_MONTH_NAMES: tuple[str, ...] = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

# Where a row's working/off state came from — useful for explaining a sheet
# and for the deterministic-precedence tests.
SOURCE_SCHEDULE = "schedule"
SOURCE_OVERRIDE_OFF = "override_off"
SOURCE_OVERRIDE_EXTRA = "override_extra"


def validate_month(raw: object) -> str:
    """Validate a ``YYYY-MM`` month string.

    Year ``0000`` matches the digit shape but has no calendar — ``date(0, …)``
    raises — so it is rejected here rather than crashing the renderer later.
    """
    candidate = raw.strip() if isinstance(raw, str) else raw
    if not isinstance(candidate, str) or _MONTH_RE.fullmatch(candidate) is None or candidate[:4] == "0000":
        raise TimesheetError(
            "invalid_month",
            f"'{raw}' is not a valid month. Use the form YYYY-MM, for example '2026-08'.",
            {"value": raw},
        )
    return candidate


def split_month(month: str) -> tuple[int, int]:
    """Return ``(year, month_number)`` for a validated ``YYYY-MM`` string."""
    validated = validate_month(month)
    return int(validated[:4]), int(validated[5:7])


def month_title(month: str) -> str:
    """German month heading, e.g. ``'März 2027'``."""
    year, number = split_month(month)
    return f"{GERMAN_MONTH_NAMES[number]} {year}"


def german_date_label(day: date) -> str:
    """Row label, e.g. ``'Mo, 01.03.2027'``."""
    return f"{GERMAN_WEEKDAY_ABBREVIATIONS[day.weekday()]}, {day.strftime('%d.%m.%Y')}"


@dataclass(frozen=True)
class DayRow:
    """One calendar date of the month, already resolved."""

    date: date
    label: str
    weekday: str
    working: bool
    source: str

    @property
    def iso(self) -> str:
        return self.date.isoformat()


@dataclass(frozen=True)
class MonthLayout:
    """Every calendar date of one month for one worker, in order."""

    worker_id: str
    display_name: str
    month: str
    year: int
    month_number: int
    title: str
    rows: tuple[DayRow, ...]

    @property
    def working_rows(self) -> tuple[DayRow, ...]:
        return tuple(row for row in self.rows if row.working)

    @property
    def off_rows(self) -> tuple[DayRow, ...]:
        return tuple(row for row in self.rows if not row.working)

    def by_date(self) -> dict[str, DayRow]:
        """ISO date -> row, for callers that resolve a single day (task 3)."""
        return {row.iso: row for row in self.rows}


def _override_dates(record: Mapping[str, Any], month: str, kind: str) -> frozenset[str]:
    overrides = record.get("month_overrides") or {}
    if not isinstance(overrides, Mapping):
        raise TimesheetError(
            "invalid_overrides",
            "The worker's month exceptions are not readable. Please register the worker again.",
            {"worker_id": record.get("id")},
        )
    entry = overrides.get(month) or {}
    if not isinstance(entry, Mapping):
        raise TimesheetError(
            "invalid_overrides",
            f"The month exceptions for {month} are not readable. Please register the worker again.",
            {"worker_id": record.get("id"), "month": month},
        )
    values = entry.get(kind) or []
    if isinstance(values, str) or not hasattr(values, "__iter__"):
        raise TimesheetError(
            "invalid_overrides",
            f"The '{kind}' dates for {month} are not readable. Please register the worker again.",
            {"worker_id": record.get("id"), "month": month},
        )
    return frozenset(str(value) for value in values)


def build_month_layout(record: Mapping[str, Any], month: str) -> MonthLayout:
    """Resolve a worker record plus ``YYYY-MM`` into an ordered month layout.

    Every calendar date of the month appears exactly once — 28, 29, 30 or 31
    rows, leap February included, because the row count comes from
    :func:`calendar.monthrange` rather than from any hand-written table.
    """
    validated_month = validate_month(month)
    year, number = split_month(validated_month)

    working_weekdays = frozenset(record.get("working_weekdays") or ())
    unknown = sorted(working_weekdays - set(WEEKDAYS))
    if unknown:
        raise TimesheetError(
            "invalid_weekdays",
            f"The worker's schedule contains unknown weekday(s): {', '.join(unknown)}.",
            {"worker_id": record.get("id"), "unknown": unknown},
        )

    off_dates = _override_dates(record, validated_month, "off")
    extra_dates = _override_dates(record, validated_month, "extra")
    conflict = sorted(off_dates & extra_dates)
    if conflict:
        # Registration rejects this, so reaching it means the stored record was
        # edited by hand; refusing beats silently picking a winner.
        raise TimesheetError(
            "override_conflict",
            f"These dates in {validated_month} are marked both as day off and as extra working day: "
            f"{', '.join(conflict)}. Please register the worker again with only one of them.",
            {"worker_id": record.get("id"), "month": validated_month, "dates": conflict},
        )

    _, day_count = calendar.monthrange(year, number)
    rows: list[DayRow] = []
    for day_number in range(1, day_count + 1):
        day = date(year, number, day_number)
        iso = day.isoformat()
        weekday = WEEKDAYS[day.weekday()]
        if iso in off_dates:
            working, source = False, SOURCE_OVERRIDE_OFF
        elif iso in extra_dates:
            working, source = True, SOURCE_OVERRIDE_EXTRA
        else:
            working, source = weekday in working_weekdays, SOURCE_SCHEDULE
        rows.append(
            DayRow(date=day, label=german_date_label(day), weekday=weekday, working=working, source=source)
        )

    return MonthLayout(
        worker_id=str(record.get("id") or ""),
        display_name=str(record.get("display_name") or ""),
        month=validated_month,
        year=year,
        month_number=number,
        title=month_title(validated_month),
        rows=tuple(rows),
    )
