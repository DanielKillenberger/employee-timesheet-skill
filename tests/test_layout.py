"""Month layout model: month lengths, leap February, German labels, precedence."""

from __future__ import annotations

import calendar
from datetime import date

import pytest

from lib.layout import (
    SOURCE_OVERRIDE_EXTRA,
    SOURCE_OVERRIDE_OFF,
    SOURCE_SCHEDULE,
    build_month_layout,
    german_date_label,
    month_title,
    validate_month,
)
from lib.errors import TimesheetError


def worker(**overrides):
    record = {
        "id": "anna",
        "display_name": "Anna Muster",
        "working_weekdays": ["mon", "tue", "wed", "thu", "fri"],
        "hourly_rate": "7.50",
        "currency": "CHF",
        "month_overrides": {},
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------
# AC2/AC6 — every date exactly once, all month lengths, leap February
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("month", "expected_days"),
    [
        ("2027-02", 28),  # ordinary February
        ("2028-02", 29),  # leap February
        ("2000-02", 29),  # century leap year
        ("1900-02", 28),  # century non-leap year
        ("2027-04", 30),
        ("2027-03", 31),
        ("2027-12", 31),
    ],
)
def test_every_calendar_date_appears_exactly_once(month: str, expected_days: int) -> None:
    layout = build_month_layout(worker(), month)
    assert len(layout.rows) == expected_days
    isos = [row.iso for row in layout.rows]
    assert len(set(isos)) == expected_days
    assert isos == sorted(isos)
    year, number = int(month[:4]), int(month[5:7])
    assert isos[0] == date(year, number, 1).isoformat()
    assert isos[-1] == date(year, number, calendar.monthrange(year, number)[1]).isoformat()


def test_leap_february_includes_the_29th() -> None:
    layout = build_month_layout(worker(), "2028-02")
    assert layout.rows[-1].iso == "2028-02-29"
    assert layout.rows[-1].label == "Di, 29.02.2028"


# --------------------------------------------------------------------------
# German labels
# --------------------------------------------------------------------------


def test_month_title_is_german() -> None:
    assert month_title("2027-03") == "März 2027"
    assert month_title("2027-12") == "Dezember 2027"
    assert build_month_layout(worker(), "2027-01").title == "Januar 2027"


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2027, 3, 1), "Mo, 01.03.2027"),
        (date(2027, 3, 7), "So, 07.03.2027"),
        (date(2027, 3, 6), "Sa, 06.03.2027"),
        (date(2027, 12, 31), "Fr, 31.12.2027"),
    ],
)
def test_day_labels_use_german_abbreviations_and_dotted_dates(day: date, expected: str) -> None:
    assert german_date_label(day) == expected


def test_weekday_key_matches_the_calendar() -> None:
    layout = build_month_layout(worker(), "2027-03")
    assert [row.weekday for row in layout.rows[:7]] == [
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ]


# --------------------------------------------------------------------------
# AC3 — schedule + override precedence
# --------------------------------------------------------------------------


def test_recurring_schedule_marks_weekends_off() -> None:
    layout = build_month_layout(worker(), "2027-03")
    off = {row.iso for row in layout.off_rows}
    assert off == {
        "2027-03-06",
        "2027-03-07",
        "2027-03-13",
        "2027-03-14",
        "2027-03-20",
        "2027-03-21",
        "2027-03-27",
        "2027-03-28",
    }
    assert all(row.source == SOURCE_SCHEDULE for row in layout.rows)


def test_month_override_off_beats_the_schedule() -> None:
    record = worker(month_overrides={"2027-03": {"off": ["2027-03-02"], "extra": []}})
    row = build_month_layout(record, "2027-03").by_date()["2027-03-02"]
    assert row.working is False
    assert row.source == SOURCE_OVERRIDE_OFF


def test_month_override_extra_beats_the_schedule() -> None:
    record = worker(month_overrides={"2027-03": {"off": [], "extra": ["2027-03-06"]}})
    row = build_month_layout(record, "2027-03").by_date()["2027-03-06"]
    assert row.working is True
    assert row.source == SOURCE_OVERRIDE_EXTRA


def test_overrides_apply_only_to_their_own_month() -> None:
    record = worker(month_overrides={"2027-03": {"off": ["2027-03-02"], "extra": []}})
    april = build_month_layout(record, "2027-04")
    assert all(row.source == SOURCE_SCHEDULE for row in april.rows)
    assert april.by_date()["2027-04-02"].working is True  # a Friday, still working


def test_resolution_is_deterministic_across_repeated_builds() -> None:
    record = worker(month_overrides={"2027-03": {"off": ["2027-03-02"], "extra": ["2027-03-06"]}})
    first = build_month_layout(record, "2027-03")
    second = build_month_layout(record, "2027-03")
    assert first.rows == second.rows


def test_hand_edited_record_with_conflicting_override_is_refused() -> None:
    record = worker(month_overrides={"2027-03": {"off": ["2027-03-02"], "extra": ["2027-03-02"]}})
    with pytest.raises(TimesheetError) as excinfo:
        build_month_layout(record, "2027-03")
    assert excinfo.value.code == "override_conflict"


def test_empty_schedule_yields_only_override_working_days() -> None:
    record = worker(
        working_weekdays=[],
        month_overrides={"2027-03": {"off": [], "extra": ["2027-03-06"]}},
    )
    layout = build_month_layout(record, "2027-03")
    assert [row.iso for row in layout.working_rows] == ["2027-03-06"]
    assert len(layout.off_rows) == 30


def test_unknown_weekday_in_a_record_is_refused() -> None:
    with pytest.raises(TimesheetError) as excinfo:
        build_month_layout(worker(working_weekdays=["mon", "funday"]), "2027-03")
    assert excinfo.value.code == "invalid_weekdays"


# --------------------------------------------------------------------------
# month grammar
# --------------------------------------------------------------------------


@pytest.mark.parametrize("month", ["2027-13", "2027-00", "27-03", "2027/03", "2027-3", "", "März"])
def test_invalid_months_are_refused(month: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        validate_month(month)
    assert excinfo.value.code == "invalid_month"


def test_invalid_month_is_refused_by_the_layout_builder() -> None:
    with pytest.raises(TimesheetError) as excinfo:
        build_month_layout(worker(), "2027-13")
    assert excinfo.value.code == "invalid_month"


def test_layout_carries_worker_identity() -> None:
    layout = build_month_layout(worker(), "2027-03")
    assert layout.worker_id == "anna"
    assert layout.display_name == "Anna Muster"
    assert (layout.year, layout.month_number) == (2027, 3)
