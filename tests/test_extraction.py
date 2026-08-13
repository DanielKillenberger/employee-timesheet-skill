"""Extraction validation, flags, identity gates, confirmation and evidence (AC5/AC9).

The month used throughout is 2026-08 for a worker who works Mondays and
Tuesdays, so a whole month fits in a handful of entries: working days are the
3rd, 4th, 10th, 11th, 17th, 18th, 24th, 25th and 31st.
"""

from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

import timesheet
from lib import extraction as ex
from lib import registry as reg
from lib.datadir import resolve_data_dir
from lib.errors import TimesheetError
from lib.layout import build_month_layout

SCRIPTS_DIR = Path(timesheet.__file__).resolve().parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MONTH = "2026-08"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def data_dir(tmp_path: Path):
    directory = resolve_data_dir(str(tmp_path / "data"))
    reg.register_worker(
        directory,
        worker_id="anna",
        display_name="Anna Muster",
        weekdays="mon,tue",
        rate="7.50",
    )
    return directory


def layout_for(data_dir, month: str = MONTH):
    return build_month_layout(reg.get_worker(data_dir, "anna"), month)


def parse(document, data_dir, month: str = MONTH):
    return ex.parse_entries_document(document, layout=layout_for(data_dir, month), worker_id="anna")


def session_for(document, data_dir, month: str = MONTH, evidence=()):
    return ex.build_session(
        record=reg.get_worker(data_dir, "anna"),
        layout=layout_for(data_dir, month),
        document=parse(document, data_dir, month),
        evidence=evidence,
    )


def entry(day: int, kind: str, value=None, confidence: str = "high", **extra) -> dict:
    item = {"date": f"2026-08-{day:02d}", "kind": kind, "confidence": confidence, **extra}
    if value is not None:
        item["value"] = value
    return item


def document(entries: list[dict], **extra) -> dict:
    return {"schema_version": 1, "month": MONTH, "entries": entries, **extra}


def day_of(session, day: int) -> dict:
    return next(item for item in session["days"] if item["date"] == f"2026-08-{day:02d}")


def error_code(callable_, *args, **kwargs) -> str:
    with pytest.raises(TimesheetError) as excinfo:
        callable_(*args, **kwargs)
    return excinfo.value.code


# --------------------------------------------------------------------------
# schema: what no confirmation can fix (AC5, hard rejections)
# --------------------------------------------------------------------------


def test_clean_fixture_parses(data_dir) -> None:
    parsed = parse(fixture("entries-clean"), data_dir)
    assert len(parsed["entries"]) == 9
    assert parsed["entries"]["2026-08-03"]["value"] == "7.5"
    assert parsed["entries"]["2026-08-31"]["kind"] == "zero"


def test_duplicate_date_is_rejected(data_dir) -> None:
    assert error_code(parse, fixture("entries-duplicate-date"), data_dir) == "duplicate_date"


def test_more_than_24_hours_is_rejected(data_dir) -> None:
    assert error_code(parse, fixture("entries-impossible-hours"), data_dir) == "impossible_hours"


@pytest.mark.parametrize("value", ["-3", "7.555", "1e2", "NaN", "Infinity", "7.5.5", "  ", "eight"])
def test_hours_outside_the_money_grammar_are_rejected(data_dir, value) -> None:
    assert error_code(parse, document([entry(3, "value", value)]), data_dir) == "invalid_hours"


def test_exactly_24_hours_is_allowed_but_flagged(data_dir) -> None:
    session = session_for(document([entry(3, "value", "24")]), data_dir)
    assert day_of(session, 3)["flags"] == [ex.FLAG_IMPLAUSIBLE]


def test_a_date_that_does_not_exist_is_rejected(data_dir) -> None:
    doc = {"schema_version": 1, "entries": [{"date": "2027-02-29", "kind": "blank", "confidence": "high"}]}
    assert error_code(parse, doc, data_dir, "2027-02") == "invalid_date"


def test_leap_day_is_accepted_in_a_leap_year(data_dir) -> None:
    doc = {"schema_version": 1, "entries": [{"date": "2028-02-29", "kind": "value", "value": "8", "confidence": "high"}]}
    assert "2028-02-29" in parse(doc, data_dir, "2028-02")["entries"]


def test_a_date_from_another_month_is_rejected(data_dir) -> None:
    doc = {"schema_version": 1, "entries": [{"date": "2026-09-01", "kind": "blank", "confidence": "high"}]}
    assert error_code(parse, doc, data_dir) == "date_outside_month"


@pytest.mark.parametrize(
    "doc",
    [
        {"schema_version": 1, "entries": [], "unexpected": 1},
        {"schema_version": 1, "entries": [{"date": "2026-08-03", "kind": "blank", "cofidence": "high"}]},
        {"schema_version": 1, "entries": [entry(3, "sortof", confidence="high")]},
        {"schema_version": 1, "entries": [entry(3, "value", "8", confidence="fairly-sure")]},
        {"schema_version": 1, "entries": [entry(3, "value", confidence="high")]},
        {"schema_version": 1, "entries": [entry(3, "blank", "8", confidence="high")]},
        {"schema_version": 1, "entries": "not-a-list"},
        {"schema_version": 1, "entries": ["not-an-object"]},
        {"schema_version": 1, "entries": [entry(3, "value", "8", note="x" * 201)]},
        {"schema_version": 1, "entries": [entry(3, "value", "8", note="line\x00break")]},
    ],
)
def test_malformed_documents_are_rejected(data_dir, doc) -> None:
    assert error_code(parse, doc, data_dir) in {"invalid_entries", "invalid_date"}


def test_unknown_schema_version_is_rejected(data_dir) -> None:
    assert error_code(parse, {"schema_version": 99, "entries": []}, data_dir) == "unsupported_entries_version"


def test_document_worker_and_month_must_match_the_request(data_dir) -> None:
    assert error_code(parse, document([], worker_id="bea"), data_dir) == "worker_mismatch"
    assert error_code(parse, {"schema_version": 1, "month": "2026-09", "entries": []}, data_dir) == "month_mismatch"


@pytest.mark.parametrize(
    "entry_json",
    [
        {"date": "2026-08-03", "kind": "blank", "value": None, "confidence": "high"},
        {"date": "2026-08-03", "kind": "unreadable", "value": None, "confidence": "low"},
        {"date": "2026-08-03", "kind": "value", "value": None, "confidence": "high"},
    ],
)
def test_an_explicit_null_value_is_refused_rather_than_read_as_absent(data_dir, entry_json) -> None:
    """'value must be omitted' means omitted — null states two things at once."""
    assert error_code(parse, {"schema_version": 1, "entries": [entry_json]}, data_dir) == "invalid_entries"


@pytest.mark.parametrize("kind", ["unreadable", "not_provided"])
def test_an_explicit_null_observed_name_value_is_refused(data_dir, kind) -> None:
    doc = document([], observed_name={"kind": kind, "value": None})
    assert error_code(parse, doc, data_dir) == "invalid_observed_name"


def test_a_written_zero_is_recorded_as_zero_whichever_kind_was_used(data_dir) -> None:
    parsed = parse(document([entry(3, "value", "0"), entry(4, "zero")]), data_dir)
    assert parsed["entries"]["2026-08-03"] == {"kind": "zero", "value": "0", "confidence": "high", "note": None}
    assert parsed["entries"]["2026-08-04"]["value"] == "0"


# --------------------------------------------------------------------------
# identity (plan decision 6) — all four statuses
# --------------------------------------------------------------------------


def test_identity_matches_ignoring_case_and_extra_spaces(data_dir) -> None:
    session = session_for(fixture("entries-flagged"), data_dir)  # observed "anna  muster"
    assert session["identity"]["status"] == ex.IDENTITY_MATCHED


def test_identity_mismatch_is_recorded(data_dir) -> None:
    session = session_for(fixture("entries-name-mismatch"), data_dir)
    assert session["identity"]["status"] == ex.IDENTITY_MISMATCH
    assert session["identity"]["observed_name"] == {"kind": "value", "value": "Bea Beispiel"}


def test_identity_unreadable_and_not_provided_pass_through(data_dir) -> None:
    unreadable = session_for(document([], observed_name={"kind": "unreadable"}), data_dir)
    assert unreadable["identity"]["status"] == ex.IDENTITY_UNREADABLE
    absent = session_for(document([]), data_dir)
    assert absent["identity"]["status"] == ex.IDENTITY_NOT_PROVIDED
    assert absent["identity"]["observed_name"] == {"kind": "not_provided", "value": None}


@pytest.mark.parametrize(
    "observed",
    [
        {"kind": "value"},
        {"kind": "value", "value": "   "},
        {"kind": "unreadable", "value": "Anna"},
        {"kind": "guessed", "value": "Anna"},
        {"kind": "value", "value": "Anna", "extra": 1},
        "Anna Muster",
    ],
)
def test_malformed_observed_name_is_rejected(data_dir, observed) -> None:
    assert error_code(parse, document([], observed_name=observed), data_dir) == "invalid_observed_name"


# --------------------------------------------------------------------------
# session shape, flags and the provisional total
# --------------------------------------------------------------------------


def test_session_holds_every_calendar_date_once(data_dir) -> None:
    session = session_for(fixture("entries-clean"), data_dir)
    dates = [day["date"] for day in session["days"]]
    assert len(dates) == 31 == len(set(dates))
    assert dates[0] == "2026-08-01" and dates[-1] == "2026-08-31"


def test_days_the_sheet_never_mentioned_are_blank(data_dir) -> None:
    session = session_for(document([entry(3, "value", "7.5")]), data_dir)
    day = day_of(session, 4)  # a working Tuesday, not transcribed
    assert (day["kind"], day["source"], day["value"]) == (ex.KIND_BLANK, ex.SOURCE_NOT_REPORTED, None)
    assert day["flags"] == [ex.FLAG_BLANK_WORKING_DAY]


def test_flags_cover_every_kind_of_uncertainty(data_dir) -> None:
    session = session_for(fixture("entries-flagged"), data_dir)
    assert day_of(session, 4)["flags"] == [ex.FLAG_UNREADABLE]
    assert day_of(session, 10)["flags"] == [ex.FLAG_IMPLAUSIBLE]
    assert day_of(session, 11)["flags"] == [ex.FLAG_LOW_CONFIDENCE]
    assert day_of(session, 18)["flags"] == [ex.FLAG_BLANK_WORKING_DAY]
    assert day_of(session, 3)["flags"] == []


def test_blank_days_off_the_schedule_are_never_flagged(data_dir) -> None:
    session = session_for(fixture("entries-clean"), data_dir)
    saturday = day_of(session, 1)  # 2026-08-01 is a Saturday, not a working day
    assert saturday["working"] is False and saturday["flags"] == []


def test_hours_written_on_an_off_day_count(data_dir) -> None:
    """Reality beats the schedule (plan decision 4)."""
    session = session_for(fixture("entries-flagged"), data_dir)
    saturday = day_of(session, 15)
    assert saturday["working"] is False and saturday["value"] == "4"
    assert ex.provisional_total(session) == Decimal("65.0")


def test_provisional_total_ignores_unreadable_days(data_dir) -> None:
    with_unreadable = session_for(document([entry(3, "value", "8"), entry(4, "unreadable")]), data_dir)
    assert ex.provisional_total(with_unreadable) == Decimal("8")


def test_attention_list_names_every_open_day_and_how_to_resolve_it(data_dir) -> None:
    session = session_for(fixture("entries-flagged"), data_dir)
    items = {item["date"]: item for item in ex.attention_items(session)}
    assert set(items) == {"2026-08-04", "2026-08-10", "2026-08-11", "2026-08-18"}
    assert "--set" in items["2026-08-04"]["resolution"]
    assert items["2026-08-10"]["reasons"] == ["more than 12 hours on one day"]


# --------------------------------------------------------------------------
# confirmation gates (AC5/AC9)
# --------------------------------------------------------------------------


def confirm(session, data_dir, *, accept_identity: bool = False):
    return ex.confirm_session(
        session, reg.get_worker(data_dir, "anna"), accept_identity=accept_identity
    )


def test_confirm_refuses_while_a_working_day_is_blank(data_dir) -> None:
    session = session_for(document([entry(3, "value", "8")]), data_dir)
    with pytest.raises(TimesheetError) as excinfo:
        confirm(session, data_dir)
    assert excinfo.value.code == "blank_working_day"
    assert "2026-08-04" in excinfo.value.detail["dates"]


def test_confirm_refuses_while_a_day_is_unreadable_even_on_an_off_day(data_dir) -> None:
    entries = [entry(day, "value", "7.5") for day in (3, 4, 10, 11, 17, 18, 24, 25, 31)]
    entries.append(entry(15, "unreadable"))  # a Saturday
    session = session_for(document(entries), data_dir)
    assert error_code(confirm, session, data_dir) == "unreadable_entry"


def test_confirm_refuses_while_a_flag_is_unaddressed(data_dir) -> None:
    entries = [entry(day, "value", "7.5") for day in (3, 4, 10, 11, 17, 18, 24, 25)]
    entries.append(entry(31, "value", "14"))
    session = session_for(document(entries), data_dir)
    with pytest.raises(TimesheetError) as excinfo:
        confirm(session, data_dir)
    assert excinfo.value.code == "unconfirmed_flags"
    assert excinfo.value.detail["dates"] == ["2026-08-31"]


def test_repeating_a_flagged_value_accepts_it(data_dir) -> None:
    session = session_for(fixture("entries-flagged"), data_dir)
    ex.apply_correction(session, "2026-08-04", "0")  # unreadable -> no hours
    ex.apply_correction(session, "2026-08-18", "0")  # blank working day
    ex.apply_correction(session, "2026-08-10", "14")  # repeat: yes, really 14
    ex.apply_correction(session, "2026-08-11", "7.5")  # repeat: yes, really 7.5
    confirmation = confirm(session, data_dir)
    assert day_of(session, 10)["accepted"] is True
    assert day_of(session, 10)["flags"] == [ex.FLAG_IMPLAUSIBLE]  # recorded, not erased
    assert confirmation["total_hours"] == "65.0"


def test_a_corrected_value_clears_the_flag_and_a_new_bad_one_raises_it_again(data_dir) -> None:
    session = session_for(document([entry(3, "value", "14")]), data_dir)
    ex.apply_correction(session, "2026-08-03", "8")
    day = day_of(session, 3)
    assert (day["flags"], day["corrected"], day["source"]) == ([], True, ex.SOURCE_CORRECTION)
    ex.apply_correction(session, "2026-08-03", "13")
    assert day_of(session, 3)["flags"] == [ex.FLAG_IMPLAUSIBLE]
    assert day_of(session, 3)["accepted"] is False


def test_corrections_are_validated_like_transcribed_hours(data_dir) -> None:
    session = session_for(document([]), data_dir)
    assert error_code(ex.apply_correction, session, "2026-08-03", "25") == "impossible_hours"
    assert error_code(ex.apply_correction, session, "2026-08-03", "-2") == "invalid_hours"
    assert error_code(ex.apply_correction, session, "2026-09-03", "8") == "date_outside_month"


@pytest.mark.parametrize("raw", ["2026-08-03", "=8", "2026-08-03=", "", "2026-08-03:8", None])
def test_malformed_set_arguments_are_rejected(raw) -> None:
    assert error_code(ex.parse_set_argument, raw) == "invalid_correction"


def test_set_argument_splits_date_from_hours() -> None:
    assert ex.parse_set_argument(" 2026-08-03 = 7,5 ") == ("2026-08-03", "7,5")


def test_a_day_with_no_value_can_only_be_entered_never_repeated(data_dir) -> None:
    """An uncertain *blank* has nothing to repeat back, off day or not."""
    session = session_for(document([entry(1, "blank", confidence="low")]), data_dir)
    saturday = day_of(session, 1)
    assert saturday["working"] is False and saturday["flags"] == [ex.FLAG_LOW_CONFIDENCE]
    item = next(item for item in ex.attention_items(session) if item["date"] == "2026-08-01")
    assert item["resolution"] == "correct it with --set DATE=HOURS (use 0 for no hours)"
    ex.apply_correction(session, "2026-08-01", "0")
    assert [item["date"] for item in ex.attention_items(session)] == [
        f"2026-08-{day:02d}" for day in (3, 4, 10, 11, 17, 18, 24, 25, 31)
    ]


def test_identity_mismatch_blocks_until_explicitly_accepted(data_dir) -> None:
    session = session_for(fixture("entries-name-mismatch"), data_dir)
    assert error_code(confirm, session, data_dir) == "identity_unconfirmed"
    confirmation = confirm(session, data_dir, accept_identity=True)
    assert session["identity"]["accepted"] is True
    assert session["identity"]["accepted_at"] is not None
    assert confirmation["total_hours"] == "60.0"


def test_unreadable_identity_blocks_but_a_missing_name_does_not(data_dir) -> None:
    clean_entries = fixture("entries-clean")["entries"]
    unreadable = session_for(
        {"schema_version": 1, "entries": clean_entries, "observed_name": {"kind": "unreadable"}}, data_dir
    )
    assert error_code(confirm, unreadable, data_dir) == "identity_unconfirmed"
    absent = session_for({"schema_version": 1, "entries": clean_entries}, data_dir)
    assert confirm(absent, data_dir)["total_hours"] == "60.0"


def test_blockers_report_everything_that_is_still_open(data_dir) -> None:
    session = session_for(fixture("entries-flagged"), data_dir)
    session["identity"]["status"] = ex.IDENTITY_MISMATCH
    with pytest.raises(TimesheetError) as excinfo:
        confirm(session, data_dir)
    remaining = excinfo.value.detail["remaining"]
    assert remaining["identity"] == ex.IDENTITY_MISMATCH
    assert remaining["blank_working_days"] == ["2026-08-18"]
    assert remaining["unreadable_days"] == ["2026-08-04"]
    assert [item["date"] for item in remaining["flagged_days"]] == ["2026-08-10", "2026-08-11"]


# --------------------------------------------------------------------------
# confirmation result: exact totals, receipt, frozen snapshot
# --------------------------------------------------------------------------


def test_confirmation_freezes_every_day_and_a_transparent_receipt(data_dir) -> None:
    session = session_for(fixture("entries-clean"), data_dir)
    confirmation = confirm(session, data_dir)
    assert session["status"] == ex.STATUS_CONFIRMED
    assert len(confirmation["days"]) == 31
    assert confirmation["days"][0] == {
        "date": "2026-08-01",
        "label": "Sa, 01.08.2026",
        "working": False,
        "hours": "0",
        "note": None,
    }
    assert confirmation["total_hours"] == "60.0"
    assert confirmation["receipt"]["statement"] == "60.0 h x 7.50 CHF = 450.00 CHF"
    assert confirmation["snapshot"] == {
        "worker_id": "anna",
        "display_name": "Anna Muster",
        "hourly_rate": "7.50",
        "currency": "CHF",
    }


def test_leap_february_confirms_exactly_and_rounds_once(data_dir) -> None:
    """AC6's leap month end to end: 9 working days at 8.5 h, rate 7.55."""
    reg.register_worker(data_dir, worker_id="anna", rate="7.55")
    month = "2028-02"
    days = (1, 7, 8, 14, 15, 21, 22, 28, 29)
    entries = [
        {"date": f"2028-02-{day:02d}", "kind": "value", "value": "8.5", "confidence": "high"} for day in days
    ]
    session = session_for({"schema_version": 1, "entries": entries}, data_dir, month)
    assert len(session["days"]) == 29
    confirmation = confirm(session, data_dir)
    assert confirmation["total_hours"] == "76.5"
    assert confirmation["receipt"]["exact_amount"] == "577.575"
    assert confirmation["receipt"]["gross_pay"] == "577.58"  # kaufmaennisch, not 577.57
    assert confirmation["receipt"]["rounding_applied"] is True


def test_a_renamed_worker_makes_the_identity_check_start_over(data_dir) -> None:
    """The name check is worthless unless it is made against the name being frozen."""
    session = session_for(fixture("entries-clean"), data_dir)
    assert session["identity"]["status"] == ex.IDENTITY_MATCHED

    reg.register_worker(data_dir, worker_id="anna", display_name="Bea Beispiel", rate="99.00")

    assert error_code(confirm, session, data_dir) == "identity_unconfirmed"
    assert session["identity"]["status"] == ex.IDENTITY_MISMATCH
    assert session["identity"]["registered_name"] == "Bea Beispiel"

    confirmation = confirm(session, data_dir, accept_identity=True)
    assert confirmation["snapshot"]["display_name"] == "Bea Beispiel"


def test_a_rename_withdraws_an_earlier_identity_acceptance(data_dir) -> None:
    session = session_for(fixture("entries-name-mismatch"), data_dir)
    session["identity"]["accepted"] = True
    session["identity"]["accepted_at"] = "2026-08-13T00:00:00Z"

    reg.register_worker(data_dir, worker_id="anna", display_name="Carla Anders")

    assert error_code(confirm, session, data_dir) == "identity_unconfirmed"
    assert session["identity"]["accepted"] is False and session["identity"]["accepted_at"] is None


def test_snapshot_survives_a_later_re_registration(data_dir) -> None:
    """Session-layer immutability (plan decision 1); the tally is task .4's job."""
    session = session_for(fixture("entries-clean"), data_dir)
    frozen = copy.deepcopy(confirm(session, data_dir))
    ex.save_session(data_dir, session)

    reg.register_worker(data_dir, worker_id="anna", display_name="Anna Neu", rate="99.00", currency="EUR")

    reloaded = ex.load_session(data_dir, "anna", MONTH)
    assert reloaded["confirmation"] == frozen
    assert reloaded["confirmation"]["snapshot"]["hourly_rate"] == "7.50"
    assert reloaded["confirmation"]["receipt"]["gross_pay"] == "450.00"


# --------------------------------------------------------------------------
# session persistence
# --------------------------------------------------------------------------


def test_session_round_trips_through_the_data_folder(data_dir) -> None:
    session = session_for(fixture("entries-flagged"), data_dir)
    path = ex.save_session(data_dir, session)
    assert path == data_dir.path / "extractions" / "anna-2026-08.json"
    assert ex.load_session(data_dir, "anna", MONTH) == session
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_loading_a_session_that_was_never_started_is_a_plain_error(data_dir) -> None:
    assert error_code(ex.load_session, data_dir, "anna", "2026-09") == "no_session"


def test_a_session_written_by_another_version_is_refused(data_dir) -> None:
    session = session_for(fixture("entries-clean"), data_dir)
    session["schema_version"] = 99
    ex.save_session(data_dir, session)
    assert error_code(ex.load_session, data_dir, "anna", MONTH) == "unsupported_session_version"


def test_session_path_stays_inside_the_data_folder(data_dir) -> None:
    assert error_code(ex.session_path, data_dir, "../escape", MONTH) == "unsafe_path"


def write_session_file(data_dir, payload: dict) -> None:
    path = ex.session_path(data_dir, "anna", MONTH)
    data_dir.extractions_dir
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_a_truncated_session_can_never_confirm_as_a_short_month(data_dir) -> None:
    """Missing days cannot be flagged as blank, so a lost tail must be refused."""
    session = session_for(fixture("entries-clean"), data_dir)
    session["days"] = session["days"][:1]
    write_session_file(data_dir, session)
    assert error_code(ex.load_session, data_dir, "anna", MONTH) == "corrupt_session"


@pytest.mark.parametrize(
    "damage",
    [
        lambda s: s.update(worker_id="bea"),
        lambda s: s.update(month="2026-09"),
        lambda s: s.update(status="nearly"),
        lambda s: s.update(identity={"status": "matched"}),
        lambda s: s["days"].append(dict(s["days"][0])),
        lambda s: s["days"][0].pop("flags"),
        lambda s: s["days"][0].update(kind="maybe"),
        lambda s: s["days"][0].update(source="guesswork"),
        lambda s: s["days"][0].update(working="yes"),
        lambda s: s["days"][2].update(kind="value", value=None),
        lambda s: s["days"][2].update(value="99"),
        lambda s: s.update(confirmation={"total_hours": "8"}),
    ],
)
def test_a_damaged_session_is_refused_not_repaired(data_dir, damage) -> None:
    session = session_for(fixture("entries-clean"), data_dir)
    damage(session)
    write_session_file(data_dir, session)
    assert error_code(ex.load_session, data_dir, "anna", MONTH) == "corrupt_session"


def test_a_confirmed_session_must_carry_a_complete_result(data_dir) -> None:
    session = session_for(fixture("entries-clean"), data_dir)
    confirm(session, data_dir)
    del session["confirmation"]["snapshot"]["hourly_rate"]
    write_session_file(data_dir, session)
    assert error_code(ex.load_session, data_dir, "anna", MONTH) == "corrupt_session"


def test_hand_edited_flags_are_recomputed_on_load(data_dir) -> None:
    """Flags are derived data; clearing them by hand must not clear the gate."""
    session = session_for(fixture("entries-flagged"), data_dir)
    for day in session["days"]:
        day["flags"] = []
    write_session_file(data_dir, session)

    reloaded = ex.load_session(data_dir, "anna", MONTH)
    assert [item["date"] for item in ex.attention_items(reloaded)] == [
        "2026-08-04", "2026-08-10", "2026-08-11", "2026-08-18",
    ]
    assert error_code(confirm, reloaded, data_dir) == "blank_working_day"


# --------------------------------------------------------------------------
# evidence photos
# --------------------------------------------------------------------------


def photo(tmp_path: Path, name: str, payload: bytes = b"\x89PNG fake") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_photos_are_copied_under_a_content_derived_name_with_their_hash(data_dir, tmp_path) -> None:
    source = photo(tmp_path, "IMG 1234 (Anna's sheet).png")
    [record] = ex.ingest_evidence(data_dir, [str(source)], worker_id="anna", month=MONTH)

    stored = data_dir.path / "filled-timesheets" / record["stored_filename"]
    assert stored.read_bytes() == source.read_bytes()
    assert record["stored_filename"].startswith("anna-2026-08-") and record["stored_filename"].endswith(".png")
    assert len(record["sha256"]) == 64
    assert record["source_name"] == "IMG-1234-Anna-s-sheet-.png"
    if os.name == "posix":
        assert stat.S_IMODE(stored.stat().st_mode) == 0o600


def test_the_same_photo_twice_is_stored_once(data_dir, tmp_path) -> None:
    first = photo(tmp_path, "a.png")
    second = photo(tmp_path, "b.png")  # identical bytes
    records = ex.ingest_evidence(data_dir, [str(first), str(second)], worker_id="anna", month=MONTH)
    assert len(records) == 1
    assert len(list((data_dir.path / "filled-timesheets").iterdir())) == 1


def test_unsupported_and_missing_photos_are_refused(data_dir, tmp_path) -> None:
    script = photo(tmp_path, "sheet.sh", b"rm -rf /")
    assert error_code(ex.ingest_evidence, data_dir, [str(script)], worker_id="anna", month=MONTH) == (
        "unsupported_photo"
    )
    assert error_code(
        ex.ingest_evidence, data_dir, [str(tmp_path / "nope.png")], worker_id="anna", month=MONTH
    ) == "photo_missing"


# --------------------------------------------------------------------------
# CLI (the surface Claude actually drives)
# --------------------------------------------------------------------------


def run_cli(args: list[str], data_dir, stdin: str | None = None) -> tuple[int, dict]:
    process = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "timesheet.py"), *args, "--data-dir", str(data_dir.path), "--json"],
        capture_output=True,
        text=True,
        input=stdin,
    )
    stream = process.stdout if process.returncode == 0 else process.stderr
    return process.returncode, json.loads(stream)


def test_cli_validate_then_confirm_walks_the_whole_flow(data_dir, tmp_path) -> None:
    evidence = photo(tmp_path, "sheet.jpg")
    code, payload = run_cli(
        [
            "validate-extraction", "--worker", "anna", "--month", MONTH,
            "--entries", str(FIXTURES / "entries-flagged.json"),
            "--photo", str(evidence),
        ],
        data_dir,
    )
    assert code == 0
    assert payload["provisional_total_hours"] == "65.0"
    assert payload["needs_attention_count"] == 4
    assert payload["identity"]["status"] == "matched"
    assert payload["evidence"][0]["sha256"]

    code, blocked = run_cli(["confirm", "--worker", "anna", "--month", MONTH], data_dir)
    assert code == 1 and blocked["code"] == "blank_working_day"

    code, payload = run_cli(
        [
            "confirm", "--worker", "anna", "--month", MONTH,
            "--set", "2026-08-04=0", "--set", "2026-08-18=0",
            "--set", "2026-08-10=14", "--set", "2026-08-11=7.5",
        ],
        data_dir,
    )
    assert code == 0
    assert payload["total_hours"] == "65.0"
    assert payload["receipt"]["gross_pay"] == "487.50"
    assert payload["snapshot"]["hourly_rate"] == "7.50"


def test_cli_reads_entries_from_stdin(data_dir) -> None:
    code, payload = run_cli(
        ["validate-extraction", "--worker", "anna", "--month", MONTH, "--entries", "-"],
        data_dir,
        stdin=json.dumps(fixture("entries-clean")),
    )
    assert code == 0 and payload["needs_attention_count"] == 0


def test_cli_refuses_to_redo_an_extraction_without_overwrite(data_dir) -> None:
    args = [
        "validate-extraction", "--worker", "anna", "--month", MONTH,
        "--entries", str(FIXTURES / "entries-clean.json"),
    ]
    assert run_cli(args, data_dir)[0] == 0
    code, payload = run_cli(args, data_dir)
    assert code == 1 and payload["code"] == "session_exists"
    assert run_cli([*args, "--overwrite"], data_dir)[0] == 0


def test_cli_keeps_corrections_made_during_a_blocked_confirm(data_dir) -> None:
    """A long month can be worked through in several passes."""
    run_cli(
        [
            "validate-extraction", "--worker", "anna", "--month", MONTH,
            "--entries", str(FIXTURES / "entries-flagged.json"),
        ],
        data_dir,
    )
    code, payload = run_cli(
        ["confirm", "--worker", "anna", "--month", MONTH, "--set", "2026-08-18=6"], data_dir
    )
    assert code == 1 and payload["code"] == "unreadable_entry"
    session = ex.load_session(data_dir, "anna", MONTH)
    assert day_of(session, 18)["value"] == "6"
    assert session["status"] == ex.STATUS_EXTRACTED


def test_cli_refuses_to_change_an_already_confirmed_month(data_dir) -> None:
    run_cli(
        [
            "validate-extraction", "--worker", "anna", "--month", MONTH,
            "--entries", str(FIXTURES / "entries-clean.json"),
        ],
        data_dir,
    )
    code, first = run_cli(["confirm", "--worker", "anna", "--month", MONTH], data_dir)
    assert code == 0

    code, payload = run_cli(
        ["confirm", "--worker", "anna", "--month", MONTH, "--set", "2026-08-03=12"], data_dir
    )
    assert code == 1 and payload["code"] == "already_confirmed"

    code, again = run_cli(["confirm", "--worker", "anna", "--month", MONTH], data_dir)
    assert code == 0 and again["receipt"] == first["receipt"]
    assert again["confirmed_at"] == first["confirmed_at"]


def test_cli_reports_an_unknown_worker_and_a_missing_entries_file(data_dir) -> None:
    code, payload = run_cli(
        ["validate-extraction", "--worker", "bea", "--month", MONTH, "--entries", "-"], data_dir, stdin="{}"
    )
    assert code == 1 and payload["code"] == "unknown_worker"
    code, payload = run_cli(
        ["validate-extraction", "--worker", "anna", "--month", MONTH, "--entries", "/nope/entries.json"],
        data_dir,
    )
    assert code == 1 and payload["code"] == "input_missing"


def test_cli_reports_broken_json_on_stdin(data_dir) -> None:
    code, payload = run_cli(
        ["validate-extraction", "--worker", "anna", "--month", MONTH, "--entries", "-"], data_dir, stdin="{oops"
    )
    assert code == 1 and payload["code"] == "corrupt_json"
