"""Extraction validation and confirmation state (spec R3, AC5/AC9).

Claude reads the photographed sheet; **this module decides what that reading is
allowed to mean**. The division of labour is deliberate (plan decision 10):
vision produces a structured document, deterministic Python validates it, and
nothing becomes payroll until a human has confirmed every uncertain day.

Input document (documented in ``references/extraction-schema.md``)::

    {
      "schema_version": 1,
      "worker_id": "anna",                  # optional, must match --worker
      "month": "2026-08",                   # optional, must match --month
      "observed_name": {"kind": "value", "value": "Anna Muster"},
      "entries": [
        {"date": "2026-08-03", "kind": "value", "value": "7.5", "confidence": "high"},
        {"date": "2026-08-04", "kind": "unreadable", "confidence": "low", "note": "smudged"}
      ]
    }

Hard errors (nothing is written, the run fails): unknown fields, a date that is
not a real date, a date outside the month, a duplicate date, hours that do not
match the money grammar (this is what rejects negatives and >2 decimals), and
hours above 24. These are the "impossible" class — no human confirmation can
make them true.

Flags (recorded, surfaced, and blocking until addressed): ``unreadable``,
``blank_on_working_day``, ``implausible`` (>12 h) and ``low_confidence``. These
are the "uncertain" class — a human resolves them through ``confirm``.

The session file (``extractions/<worker>-<YYYY-MM>.json``) holds every calendar
date of the month, so "the sheet did not mention this day" and "this day was
blank" are the same thing and neither can be lost. On confirmation the per-day
set and a snapshot of the worker's name, rate and currency are frozen: later
re-registration can never retroactively change what was already confirmed
(plan decision 1).
"""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .datadir import DataDir, atomic_output_file, read_json, write_json_atomic
from .errors import TimesheetError
from .layout import MonthLayout, split_month, validate_month
from .money import canonical_decimal_string, parse_hours
from .pay import build_receipt, total_from_days

SESSION_VERSION = 1
DOCUMENT_VERSION = 1

STATUS_EXTRACTED = "extracted"
STATUS_CONFIRMED = "confirmed"

KIND_VALUE = "value"
KIND_ZERO = "zero"
KIND_BLANK = "blank"
KIND_UNREADABLE = "unreadable"
ENTRY_KINDS: tuple[str, ...] = (KIND_VALUE, KIND_ZERO, KIND_BLANK, KIND_UNREADABLE)

CONFIDENCES: tuple[str, ...] = ("high", "low")

NAME_KIND_VALUE = "value"
NAME_KIND_UNREADABLE = "unreadable"
NAME_KIND_NOT_PROVIDED = "not_provided"
NAME_KINDS: tuple[str, ...] = (NAME_KIND_VALUE, NAME_KIND_UNREADABLE, NAME_KIND_NOT_PROVIDED)

IDENTITY_MATCHED = "matched"
IDENTITY_MISMATCH = "mismatch"
IDENTITY_UNREADABLE = "unreadable"
IDENTITY_NOT_PROVIDED = "not_provided"
#: Statuses that block confirmation until ``--accept-identity`` (plan decision 6).
IDENTITY_BLOCKING: frozenset[str] = frozenset({IDENTITY_MISMATCH, IDENTITY_UNREADABLE})

FLAG_UNREADABLE = "unreadable"
FLAG_BLANK_WORKING_DAY = "blank_on_working_day"
FLAG_IMPLAUSIBLE = "implausible"
FLAG_LOW_CONFIDENCE = "low_confidence"

#: Flags a human can clear by repeating the value ("yes, it really says 14").
ACCEPTABLE_FLAGS: frozenset[str] = frozenset({FLAG_IMPLAUSIBLE, FLAG_LOW_CONFIDENCE})
#: Flags that carry no value to repeat — only ``--set`` resolves them.
CORRECTION_ONLY_FLAGS: frozenset[str] = frozenset({FLAG_UNREADABLE, FLAG_BLANK_WORKING_DAY})

#: Hours above this are impossible in a calendar day and are rejected outright.
MAX_DAILY_HOURS = Decimal("24")
#: Hours above this are possible but suspicious — flagged, never rejected.
IMPLAUSIBLE_ABOVE_HOURS = Decimal("12")

SOURCE_EXTRACTION = "extraction"
SOURCE_NOT_REPORTED = "not_reported"
SOURCE_CORRECTION = "correction"

DOCUMENT_FIELDS = frozenset({"schema_version", "worker_id", "month", "observed_name", "entries"})
ENTRY_FIELDS = frozenset({"date", "kind", "value", "confidence", "note"})
NAME_FIELDS = frozenset({"kind", "value"})

MAX_NOTE_LENGTH = 200

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Image/scan suffixes accepted as evidence. The list is about not copying
#: arbitrary files into the data folder, not about decoding them.
EVIDENCE_SUFFIXES: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".pdf"}
)
EVIDENCE_CHUNK = 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# input document validation
# --------------------------------------------------------------------------


def _require_mapping(raw: object, *, code: str, message: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise TimesheetError(code, message, {"value": repr(raw)[:200]})
    return raw


def _reject_unknown(present: Iterable[str], allowed: frozenset[str], *, code: str, subject: str) -> None:
    unknown = sorted(set(present) - allowed)
    if unknown:
        raise TimesheetError(
            code,
            f"{subject} contains unknown field(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}.",
            {"unknown": unknown, "allowed": sorted(allowed)},
        )


def _validate_note(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TimesheetError("invalid_entries", "A day's note must be text.", {"value": repr(raw)[:120]})
    note = " ".join(raw.split())
    if not note:
        return None
    if len(note) > MAX_NOTE_LENGTH:
        raise TimesheetError(
            "invalid_entries",
            f"A day's note is too long (maximum {MAX_NOTE_LENGTH} characters).",
            {"length": len(note)},
        )
    if _CONTROL_CHARS_RE.search(note):
        raise TimesheetError(
            "invalid_entries",
            "A day's note contains invisible control characters. Please retype it as plain text.",
            {"value": repr(note)[:120]},
        )
    return note


def _validate_entry_date(raw: object, layout: MonthLayout) -> str:
    if not isinstance(raw, str) or _DATE_RE.fullmatch(raw.strip()) is None:
        raise TimesheetError(
            "invalid_date",
            f"'{raw}' is not a date. Use the form YYYY-MM-DD, for example '{layout.rows[0].iso}'.",
            {"value": raw if isinstance(raw, str) else repr(raw)},
        )
    value = raw.strip()
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        # 2027-02-30 has the right shape and does not exist; leap years make
        # this a real transcription failure mode, not a theoretical one.
        raise TimesheetError(
            "invalid_date",
            f"'{value}' is not a real calendar date.",
            {"value": value},
        ) from exc
    iso = parsed.isoformat()
    if iso not in layout.by_date():
        raise TimesheetError(
            "date_outside_month",
            f"The date '{iso}' is not part of {layout.title} ({layout.month}). "
            "Every entry must belong to the month being evaluated.",
            {"value": iso, "month": layout.month},
        )
    return iso


def _validate_hours(raw: object, iso: str) -> Decimal:
    """Parse hours through the money grammar, then apply the hard 0-24 limit.

    The grammar is what rejects negatives, exponents and >2 decimals; only the
    upper limit is checked here (plan decision 5).
    """
    hours = parse_hours(raw)
    if hours > MAX_DAILY_HOURS:
        raise TimesheetError(
            "impossible_hours",
            f"{iso} lists {hours} hours, which is more than a day has. "
            "Please check the sheet and enter a value between 0 and 24.",
            {"date": iso, "value": str(hours), "maximum": str(MAX_DAILY_HOURS)},
        )
    return hours


def validate_observed_name(raw: object) -> dict[str, Any]:
    """Validate the structured ``observed_name`` observation (plan decision 6)."""
    if raw is None:
        return {"kind": NAME_KIND_NOT_PROVIDED, "value": None}
    entry = _require_mapping(
        raw,
        code="invalid_observed_name",
        message=(
            "'observed_name' must be an object such as "
            '{"kind": "value", "value": "Anna Muster"} or {"kind": "not_provided"}.'
        ),
    )
    _reject_unknown(entry.keys(), NAME_FIELDS, code="invalid_observed_name", subject="'observed_name'")

    kind = entry.get("kind")
    if kind not in NAME_KINDS:
        raise TimesheetError(
            "invalid_observed_name",
            f"'observed_name.kind' must be one of: {', '.join(NAME_KINDS)} (found {kind!r}).",
            {"value": kind, "allowed": list(NAME_KINDS)},
        )

    value = entry.get("value")
    if kind == NAME_KIND_VALUE:
        if "value" not in entry or not isinstance(value, str) or not value.strip():
            raise TimesheetError(
                "invalid_observed_name",
                "'observed_name.value' is required (and must be non-empty text) when the name was read.",
                {"value": repr(value)[:120]},
            )
        cleaned = " ".join(value.split())
        if _CONTROL_CHARS_RE.search(cleaned):
            raise TimesheetError(
                "invalid_observed_name",
                "The name read from the sheet contains invisible control characters. "
                "Please retype it as plain text.",
                {"value": repr(cleaned)[:120]},
            )
        return {"kind": kind, "value": cleaned}

    # Presence, not emptiness: an explicit "value": null is a contradiction the
    # documented schema does not allow, so it is refused rather than ignored.
    if "value" in entry:
        raise TimesheetError(
            "invalid_observed_name",
            f"'observed_name.value' must be omitted when kind is '{kind}'.",
            {"kind": kind, "value": repr(value)[:120]},
        )
    return {"kind": kind, "value": None}


def _normalize_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def identity_status(observed: Mapping[str, Any], registered_name: str) -> str:
    """Compare the observed name with the registered one (case/whitespace-insensitive)."""
    kind = observed.get("kind")
    if kind == NAME_KIND_VALUE:
        observed_value = str(observed.get("value") or "")
        return IDENTITY_MATCHED if _normalize_name(observed_value) == _normalize_name(registered_name) else IDENTITY_MISMATCH
    if kind == NAME_KIND_UNREADABLE:
        return IDENTITY_UNREADABLE
    return IDENTITY_NOT_PROVIDED


def parse_entries_document(raw: object, *, layout: MonthLayout, worker_id: str) -> dict[str, Any]:
    """Validate the transcription document against the month being evaluated.

    Returns ``{"observed_name": {...}, "entries": {iso: {...}}}``. Every failure
    raised here is of the "no human confirmation can fix this" class.
    """
    document = _require_mapping(
        raw,
        code="invalid_entries",
        message="The entries file must contain a JSON object with an 'entries' list.",
    )
    _reject_unknown(document.keys(), DOCUMENT_FIELDS, code="invalid_entries", subject="The entries file")

    version = document.get("schema_version", DOCUMENT_VERSION)
    if version != DOCUMENT_VERSION:
        raise TimesheetError(
            "unsupported_entries_version",
            f"The entries file uses schema version {version!r}, but this skill reads version "
            f"{DOCUMENT_VERSION}.",
            {"schema_version": version, "supported": DOCUMENT_VERSION},
        )

    stated_worker = document.get("worker_id")
    if stated_worker is not None and stated_worker != worker_id:
        raise TimesheetError(
            "worker_mismatch",
            f"The entries file is for worker '{stated_worker}', but '{worker_id}' was requested. "
            "Check which sheet belongs to which worker before continuing.",
            {"document_worker_id": stated_worker, "requested_worker_id": worker_id},
        )

    stated_month = document.get("month")
    if stated_month is not None and validate_month(stated_month) != layout.month:
        raise TimesheetError(
            "month_mismatch",
            f"The entries file is for {stated_month}, but {layout.month} was requested.",
            {"document_month": stated_month, "requested_month": layout.month},
        )

    entries_raw = document.get("entries")
    if not isinstance(entries_raw, (list, tuple)):
        raise TimesheetError(
            "invalid_entries",
            "The entries file must contain an 'entries' list, one object per transcribed day.",
            {"value": repr(entries_raw)[:120]},
        )

    entries: dict[str, dict[str, Any]] = {}
    for item in entries_raw:
        entry = _require_mapping(item, code="invalid_entries", message="Each entry must be an object.")
        _reject_unknown(entry.keys(), ENTRY_FIELDS, code="invalid_entries", subject="An entry")

        iso = _validate_entry_date(entry.get("date"), layout)
        if iso in entries:
            raise TimesheetError(
                "duplicate_date",
                f"The date {iso} appears more than once in the entries. Each day may be listed only once.",
                {"date": iso},
            )

        kind = entry.get("kind")
        if kind not in ENTRY_KINDS:
            raise TimesheetError(
                "invalid_entries",
                f"{iso}: 'kind' must be one of: {', '.join(ENTRY_KINDS)} (found {kind!r}).",
                {"date": iso, "value": kind, "allowed": list(ENTRY_KINDS)},
            )

        confidence = entry.get("confidence")
        if confidence not in CONFIDENCES:
            raise TimesheetError(
                "invalid_entries",
                f"{iso}: 'confidence' must be one of: {', '.join(CONFIDENCES)} (found {confidence!r}).",
                {"date": iso, "value": confidence, "allowed": list(CONFIDENCES)},
            )

        # Presence, not emptiness: `{"kind": "blank", "value": null}` states two
        # different things and is refused instead of quietly treated as absent.
        has_value = "value" in entry
        raw_value = entry.get("value")
        if kind == KIND_VALUE:
            if not has_value or raw_value is None:
                raise TimesheetError(
                    "invalid_entries",
                    f"{iso}: 'value' is required when kind is 'value'. Use kind 'blank' for an empty "
                    "field, 'zero' for a written 0, or 'unreadable' when it cannot be read.",
                    {"date": iso},
                )
            hours = _validate_hours(raw_value, iso)
            value = canonical_decimal_string(hours)
            # A written 0 is a written 0 however it was labelled.
            kind = KIND_ZERO if hours == 0 else KIND_VALUE
        else:
            if has_value:
                raise TimesheetError(
                    "invalid_entries",
                    f"{iso}: 'value' must be omitted when kind is '{kind}'.",
                    {"date": iso, "kind": kind, "value": repr(raw_value)[:120]},
                )
            value = "0" if kind == KIND_ZERO else None

        entries[iso] = {
            "kind": kind,
            "value": value,
            "confidence": confidence,
            "note": _validate_note(entry.get("note")),
        }

    return {"observed_name": validate_observed_name(document.get("observed_name")), "entries": entries}


# --------------------------------------------------------------------------
# flags
# --------------------------------------------------------------------------


def compute_flags(day: Mapping[str, Any]) -> list[str]:
    """Everything about this day that a human still has to look at."""
    flags: list[str] = []
    kind = day.get("kind")
    if kind == KIND_UNREADABLE:
        flags.append(FLAG_UNREADABLE)
    elif kind == KIND_BLANK and day.get("working"):
        flags.append(FLAG_BLANK_WORKING_DAY)
    elif kind in (KIND_VALUE, KIND_ZERO):
        value = day.get("value")
        if value is not None and parse_hours(value) > IMPLAUSIBLE_ABOVE_HOURS:
            flags.append(FLAG_IMPLAUSIBLE)
    if day.get("confidence") == "low" and kind != KIND_UNREADABLE:
        flags.append(FLAG_LOW_CONFIDENCE)
    return flags


FLAG_EXPLANATIONS = {
    FLAG_UNREADABLE: "the hours could not be read",
    FLAG_BLANK_WORKING_DAY: "a working day was left empty",
    FLAG_IMPLAUSIBLE: f"more than {IMPLAUSIBLE_ABOVE_HOURS} hours on one day",
    FLAG_LOW_CONFIDENCE: "the reading was uncertain",
}


def day_needs_attention(day: Mapping[str, Any]) -> bool:
    return bool(day.get("flags")) and not day.get("accepted")


def attention_items(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every day still standing between this session and a payroll result."""
    items: list[dict[str, Any]] = []
    for day in session["days"]:
        if not day_needs_attention(day):
            continue
        flags = list(day["flags"])
        items.append(
            {
                "date": day["date"],
                "label": day["label"],
                "working": day["working"],
                "kind": day["kind"],
                "value": day["value"],
                "confidence": day["confidence"],
                "flags": flags,
                "reasons": [FLAG_EXPLANATIONS[flag] for flag in flags],
                "resolution": (
                    # A day with no value has nothing to repeat, so accepting it
                    # is not an option — it has to be entered.
                    "correct it with --set DATE=HOURS (use 0 for no hours)"
                    if set(flags) & CORRECTION_ONLY_FLAGS or day["value"] is None
                    else "repeat the value with --set DATE=HOURS to accept it, or set a corrected one"
                ),
            }
        )
    return items


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------


def session_path(data_dir: DataDir, worker_id: str, month: str) -> Path:
    """Session file path, resolved and asserted beneath the data folder."""
    return data_dir.child("extractions", f"{worker_id}-{validate_month(month)}.json")


def build_session(
    *,
    record: Mapping[str, Any],
    layout: MonthLayout,
    document: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    """Turn a validated document into a full-month session (every date present)."""
    entries = document["entries"]
    observed_name = document["observed_name"]
    now = created_at or _now()

    days: list[dict[str, Any]] = []
    for row in layout.rows:
        entry = entries.get(row.iso)
        day = {
            "date": row.iso,
            "label": row.label,
            "weekday": row.weekday,
            "working": row.working,
            "kind": entry["kind"] if entry else KIND_BLANK,
            "value": entry["value"] if entry else None,
            "confidence": entry["confidence"] if entry else "high",
            "note": entry["note"] if entry else None,
            "source": SOURCE_EXTRACTION if entry else SOURCE_NOT_REPORTED,
            "corrected": False,
            "accepted": False,
        }
        day["flags"] = compute_flags(day)
        days.append(day)

    return {
        "schema_version": SESSION_VERSION,
        "worker_id": record["id"],
        "month": layout.month,
        "month_title": layout.title,
        "status": STATUS_EXTRACTED,
        "created_at": now,
        "updated_at": now,
        "identity": {
            "observed_name": dict(observed_name),
            "registered_name": record["display_name"],
            "status": identity_status(observed_name, record["display_name"]),
            "accepted": False,
            "accepted_at": None,
        },
        "evidence": [dict(item) for item in evidence],
        "days": days,
        "confirmation": None,
    }


def provisional_total(session: Mapping[str, Any]) -> Decimal:
    """Exact total of the days that could be read — unreadables contribute nothing."""
    return total_from_days(session["days"])


DAY_FIELDS = frozenset(
    {"date", "label", "weekday", "working", "kind", "value", "confidence", "note", "source", "corrected", "accepted", "flags"}
)
DAY_SOURCES: frozenset[str] = frozenset({SOURCE_EXTRACTION, SOURCE_NOT_REPORTED, SOURCE_CORRECTION})
KNOWN_FLAGS: frozenset[str] = ACCEPTABLE_FLAGS | CORRECTION_ONLY_FLAGS
CONFIRMATION_FIELDS = frozenset({"confirmed_at", "snapshot", "total_hours", "receipt", "days"})


def _corrupt(path: Path, problem: str, **detail: Any) -> TimesheetError:
    return TimesheetError(
        "corrupt_session",
        f"The extraction file '{path}' is not usable: {problem}. Run 'validate-extraction' again "
        "with --overwrite to redo the transcription.",
        {"path": str(path), "problem": problem, **detail},
    )


def month_dates(month: str) -> list[str]:
    """Every calendar date of ``YYYY-MM`` in order — the shape a session must have."""
    year, number = split_month(month)
    _, day_count = calendar.monthrange(year, number)
    return [date(year, number, day).isoformat() for day in range(1, day_count + 1)]


def _validate_loaded_session(payload: Any, path: Path, worker_id: str, month: str) -> dict[str, Any]:
    """Check a session file thoroughly enough to trust it with payroll.

    A session that lost days (a truncated file, a hand edit) would otherwise
    confirm as a short month: dates that are simply absent cannot be flagged as
    blank working days. So the calendar shape is verified, not assumed, and the
    flags are recomputed from the day data rather than trusted as stored.
    """
    if not isinstance(payload, dict):
        raise _corrupt(path, "it does not contain a session object")

    version = payload.get("schema_version")
    if version != SESSION_VERSION:
        raise TimesheetError(
            "unsupported_session_version",
            f"The extraction file '{path}' was written by a different version "
            f"(found {version!r}, expected {SESSION_VERSION}).",
            {"path": str(path), "schema_version": version},
        )

    if payload.get("worker_id") != worker_id or payload.get("month") != month:
        raise _corrupt(
            path,
            "it belongs to a different worker or month",
            found={"worker_id": payload.get("worker_id"), "month": payload.get("month")},
            expected={"worker_id": worker_id, "month": month},
        )

    status = payload.get("status")
    if status not in (STATUS_EXTRACTED, STATUS_CONFIRMED):
        raise _corrupt(path, f"its status {status!r} is not recognised")

    identity = payload.get("identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("observed_name"), dict):
        raise _corrupt(path, "the recorded worker-name observation is missing")
    observed = identity["observed_name"]
    if observed.get("kind") not in NAME_KINDS or identity.get("status") not in {
        IDENTITY_MATCHED,
        IDENTITY_MISMATCH,
        IDENTITY_UNREADABLE,
        IDENTITY_NOT_PROVIDED,
    }:
        raise _corrupt(path, "the recorded worker-name observation is not readable")
    if not isinstance(identity.get("accepted"), bool) or not isinstance(identity.get("registered_name"), str):
        raise _corrupt(path, "the recorded worker-name observation is not readable")

    days = payload.get("days")
    if not isinstance(days, list):
        raise _corrupt(path, "it has no list of days")
    expected = month_dates(month)
    if [day.get("date") if isinstance(day, dict) else None for day in days] != expected:
        raise _corrupt(
            path,
            f"it does not hold every day of {month} exactly once, in order",
            expected_days=len(expected),
            found_days=len(days),
        )

    for day in days:
        missing = sorted(DAY_FIELDS - set(day))
        if missing:
            raise _corrupt(path, f"{day['date']} is missing: {', '.join(missing)}")
        if day["kind"] not in ENTRY_KINDS or day["confidence"] not in CONFIDENCES:
            raise _corrupt(path, f"{day['date']} has an unknown kind or confidence")
        if day["source"] not in DAY_SOURCES:
            raise _corrupt(path, f"{day['date']} has an unknown source")
        if not all(isinstance(day[field], bool) for field in ("working", "corrected", "accepted")):
            raise _corrupt(path, f"{day['date']} has a malformed yes/no field")
        if day["note"] is not None and not isinstance(day["note"], str):
            raise _corrupt(path, f"{day['date']} has a malformed note")
        if not isinstance(day["flags"], list) or set(day["flags"]) - KNOWN_FLAGS:
            raise _corrupt(path, f"{day['date']} has unknown flags")
        if day["value"] is not None:
            try:
                _validate_hours(day["value"], day["date"])
            except TimesheetError as exc:
                raise _corrupt(path, f"{day['date']} holds unusable hours ({exc.message})") from exc
        elif day["kind"] in (KIND_VALUE, KIND_ZERO):
            raise _corrupt(path, f"{day['date']} is recorded as read but has no hours")
        # Flags are derived data: recompute them so a hand-edited file cannot
        # drop a day out of the attention list.
        day["flags"] = compute_flags(day)

    confirmation = payload.get("confirmation")
    if status == STATUS_CONFIRMED:
        if not isinstance(confirmation, dict) or sorted(confirmation) != sorted(CONFIRMATION_FIELDS):
            raise _corrupt(path, "the confirmed result is incomplete")
        snapshot = confirmation["snapshot"]
        if not isinstance(snapshot, dict) or not {
            "worker_id",
            "display_name",
            "hourly_rate",
            "currency",
        } <= set(snapshot):
            raise _corrupt(path, "the confirmed result has no complete worker snapshot")
        if not isinstance(confirmation.get("receipt"), dict) or not isinstance(confirmation["days"], list):
            raise _corrupt(path, "the confirmed result is incomplete")
    elif confirmation is not None:
        raise _corrupt(path, "it carries a confirmed result although it is not confirmed")

    return payload


def load_session(data_dir: DataDir, worker_id: str, month: str) -> dict[str, Any]:
    path = session_path(data_dir, worker_id, month)
    try:
        payload = read_json(path)
    except FileNotFoundError as exc:
        raise TimesheetError(
            "no_session",
            f"No extraction has been recorded for worker '{worker_id}' and {month} yet. "
            "Run 'validate-extraction' with the transcribed entries first.",
            {"worker_id": worker_id, "month": month, "path": str(path)},
        ) from exc
    return _validate_loaded_session(payload, path, worker_id, validate_month(month))


def save_session(data_dir: DataDir, session: Mapping[str, Any]) -> Path:
    data_dir.extractions_dir  # ensure the folder exists, owner-only
    path = session_path(data_dir, session["worker_id"], session["month"])
    write_json_atomic(path, session)
    return path


# --------------------------------------------------------------------------
# corrections and confirmation
# --------------------------------------------------------------------------


def parse_set_argument(raw: object) -> tuple[str, str]:
    """Split a ``--set DATE=HOURS`` argument into its two halves."""
    iso, sep, hours = raw.partition("=") if isinstance(raw, str) else ("", "", "")
    if not sep or not iso.strip() or not hours.strip():
        raise TimesheetError(
            "invalid_correction",
            f"'{raw}' is not a valid --set value. Use DATE=HOURS, for example --set 2026-08-04=7.5.",
            {"value": raw if isinstance(raw, str) else repr(raw)},
        )
    return iso.strip(), hours.strip()


def apply_correction(session: dict[str, Any], raw_date: str, raw_hours: str) -> dict[str, Any]:
    """Apply one ``--set DATE=HOURS`` correction.

    Repeating a day's current value is how a human *accepts* a flagged reading
    ("yes, it really says 14 hours"); any other value replaces it and the flags
    are recomputed from scratch, so a correction can never smuggle a new
    problem past the gate.
    """
    by_date = {day["date"]: day for day in session["days"]}
    day = by_date.get(raw_date)
    if day is None:
        raise TimesheetError(
            "date_outside_month",
            f"The date '{raw_date}' is not part of {session['month']}, so it cannot be corrected.",
            {"date": raw_date, "month": session["month"], "known_dates": len(by_date)},
        )

    hours = _validate_hours(raw_hours, raw_date)
    canonical = canonical_decimal_string(hours)

    current = day.get("value")
    if current is not None and parse_hours(current) == hours:
        day["accepted"] = True
    else:
        day["kind"] = KIND_ZERO if hours == 0 else KIND_VALUE
        day["value"] = canonical
        day["confidence"] = "high"
        day["source"] = SOURCE_CORRECTION
        day["corrected"] = True
        day["accepted"] = False
        day["flags"] = compute_flags(day)
    return day


def refresh_identity(session: dict[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """Re-compare the observed name with the name that is about to be frozen.

    The identity check is only worth anything if it is made against the record
    the snapshot actually uses. If the worker was re-registered under a
    different display name between extraction and confirmation, the stored
    ``matched`` verdict is about a name nobody is being paid under any more, so
    it is recomputed and any earlier acceptance is withdrawn — the human has to
    look again.
    """
    identity = session["identity"]
    if identity.get("registered_name") != record["display_name"]:
        identity["registered_name"] = record["display_name"]
        identity["status"] = identity_status(identity["observed_name"], record["display_name"])
        identity["accepted"] = False
        identity["accepted_at"] = None
    return identity


def confirmation_blockers(session: Mapping[str, Any]) -> dict[str, Any]:
    """Everything that still prevents confirmation, grouped by cause."""
    identity = session["identity"]
    blocked_identity = identity["status"] in IDENTITY_BLOCKING and not identity["accepted"]

    blank_working: list[str] = []
    unreadable: list[str] = []
    flagged: list[dict[str, Any]] = []
    for day in session["days"]:
        if not day_needs_attention(day):
            continue
        flags = set(day["flags"])
        if FLAG_BLANK_WORKING_DAY in flags:
            blank_working.append(day["date"])
        elif FLAG_UNREADABLE in flags:
            unreadable.append(day["date"])
        else:
            flagged.append({"date": day["date"], "value": day["value"], "flags": sorted(flags)})

    return {
        "identity": identity["status"] if blocked_identity else None,
        "blank_working_days": blank_working,
        "unreadable_days": unreadable,
        "flagged_days": flagged,
    }


def _raise_blocked(blockers: Mapping[str, Any]) -> None:
    detail = {"remaining": dict(blockers)}

    if blockers["identity"]:
        reason = (
            "does not match the registered name"
            if blockers["identity"] == IDENTITY_MISMATCH
            else "could not be read"
        )
        raise TimesheetError(
            "identity_unconfirmed",
            f"The worker name on the sheet {reason}. Check that this sheet really belongs to this "
            "worker, then repeat the command with --accept-identity to confirm it explicitly.",
            {**detail, "identity_status": blockers["identity"]},
        )

    if blockers["blank_working_days"]:
        dates = ", ".join(blockers["blank_working_days"])
        raise TimesheetError(
            "blank_working_day",
            f"These working days have no hours on the sheet: {dates}. Enter each one with "
            "--set DATE=HOURS (use 0 if no hours were worked) before confirming.",
            {**detail, "dates": blockers["blank_working_days"]},
        )

    if blockers["unreadable_days"]:
        dates = ", ".join(blockers["unreadable_days"])
        raise TimesheetError(
            "unreadable_entry",
            f"These days could not be read from the sheet: {dates}. Enter each one with "
            "--set DATE=HOURS (use 0 if no hours were worked) before confirming.",
            {**detail, "dates": blockers["unreadable_days"]},
        )

    if blockers["flagged_days"]:
        described = ", ".join(
            f"{item['date']} ({', '.join(FLAG_EXPLANATIONS[flag] for flag in item['flags'])})"
            for item in blockers["flagged_days"]
        )
        raise TimesheetError(
            "unconfirmed_flags",
            f"These days still need a decision: {described}. Repeat the value with "
            "--set DATE=HOURS to accept it, or set the corrected hours (use 0 for no hours).",
            {**detail, "dates": [item["date"] for item in blockers["flagged_days"]]},
        )


def confirmed_days(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The frozen per-day set: every calendar date with its confirmed hours."""
    days: list[dict[str, Any]] = []
    for day in session["days"]:
        value = day["value"]
        days.append(
            {
                "date": day["date"],
                "label": day["label"],
                "working": day["working"],
                "hours": value if value is not None else "0",
                "note": day["note"],
            }
        )
    return days


def confirm_session(
    session: dict[str, Any],
    record: Mapping[str, Any],
    *,
    accept_identity: bool = False,
    confirmed_at: str | None = None,
) -> dict[str, Any]:
    """Freeze the session into a payroll-usable result, or refuse with a reason.

    On success the per-day hours AND a snapshot of the worker's name, rate and
    currency are frozen. ``tally`` reads only that snapshot, so re-registering
    the worker afterwards cannot silently change an already-confirmed payment
    (plan decision 1).
    """
    identity = refresh_identity(session, record)
    if accept_identity and identity["status"] in IDENTITY_BLOCKING:
        identity["accepted"] = True
        identity["accepted_at"] = confirmed_at or _now()

    blockers = confirmation_blockers(session)
    _raise_blocked(blockers)

    total = total_from_days(session["days"])
    now = confirmed_at or _now()
    session["status"] = STATUS_CONFIRMED
    session["updated_at"] = now
    session["confirmation"] = {
        "confirmed_at": now,
        "snapshot": {
            "worker_id": record["id"],
            "display_name": record["display_name"],
            "hourly_rate": record["hourly_rate"],
            "currency": record["currency"],
        },
        "total_hours": canonical_decimal_string(total),
        "receipt": build_receipt(total, record["hourly_rate"], record["currency"]),
        "days": confirmed_days(session),
    }
    return session["confirmation"]


# --------------------------------------------------------------------------
# evidence photos
# --------------------------------------------------------------------------


def sanitize_evidence_name(name: str) -> str:
    """Reduce a source filename to something safe to record and to reuse."""
    cleaned = _UNSAFE_NAME_RE.sub("-", Path(name).name).strip("-.") or "photo"
    return cleaned[:80]


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(EVIDENCE_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def ingest_evidence(
    data_dir: DataDir, paths: Sequence[str], *, worker_id: str, month: str
) -> list[dict[str, Any]]:
    """Copy photos into the data folder and record filename + SHA-256.

    The stored name is derived from the worker, month and content hash, so the
    same photo ingested twice lands in the same file rather than accumulating
    copies, and no attacker-controlled filename ever reaches the filesystem.
    """
    validated_month = validate_month(month)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in paths:
        source = Path(raw).expanduser()
        if not source.is_file():
            raise TimesheetError(
                "photo_missing",
                f"The photo '{source}' does not exist.",
                {"path": str(source)},
            )
        suffix = source.suffix.lower()
        if suffix not in EVIDENCE_SUFFIXES:
            raise TimesheetError(
                "unsupported_photo",
                f"'{source.name}' is not a supported image type. Use one of: "
                f"{', '.join(sorted(EVIDENCE_SUFFIXES))}.",
                {"path": str(source), "suffix": suffix},
            )

        digest, size = _hash_file(source)
        if digest in seen:
            continue
        seen.add(digest)

        target_dir = data_dir.evidence_dir
        stored_name = f"{worker_id}-{validated_month}-{digest[:16]}{suffix}"
        target = data_dir.child("filled-timesheets", stored_name)
        if not target.exists():
            with atomic_output_file(target, suffix=suffix) as tmp_path:
                with source.open("rb") as reader, tmp_path.open("wb") as writer:
                    while True:
                        chunk = reader.read(EVIDENCE_CHUNK)
                        if not chunk:
                            break
                        writer.write(chunk)
        records.append(
            {
                "stored_filename": stored_name,
                "stored_in": target_dir.name,
                "source_name": sanitize_evidence_name(source.name),
                "sha256": digest,
                "bytes": size,
            }
        )
    return records
