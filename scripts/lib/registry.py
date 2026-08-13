"""Worker registry: validation, storage, and the export/import bundle.

A worker record is deliberately small and boring::

    {
      "id": "anna",
      "display_name": "Anna Muster",
      "working_weekdays": ["mon", "tue", "wed"],
      "hourly_rate": "7.50",          # canonical dot-notation, scale preserved
      "currency": "CHF",              # plain label, never validated as a code
      "month_overrides": {"2026-08": {"off": [...], "extra": [...]}},
      "created_at": "...", "updated_at": "..."
    }

Every write path — ``register`` and ``import-data`` alike — runs the SAME
validators (plan decision 13), so a bundle can never smuggle in a record that
registration would have rejected.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

from .datadir import DataDir, file_lock, read_json, write_json_atomic
from .errors import TimesheetError
from .layout import MONTH_PATTERN, WEEKDAYS, validate_month
from .money import canonical_decimal_string, parse_rate

WORKER_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"
_WORKER_ID_RE = re.compile(WORKER_ID_PATTERN)
# date.fromisoformat() also accepts '20260805' and '2026-W32-3'; the registry
# stores exactly one date shape, so the shape is checked before parsing.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# WEEKDAYS/MONTH_PATTERN come from lib.layout — the leaf module the registry and
# both sheet renderers share — and stay importable from here for callers that
# already read the calendar vocabulary off the registry.
_WEEKDAY_ORDER = {name: index for index, name in enumerate(WEEKDAYS)}

REGISTRY_VERSION = 1
BUNDLE_VERSION = 1
BUNDLE_KIND = "employee-timesheet-registry"
DEFAULT_CURRENCY = "CHF"

MAX_NAME_LENGTH = 120

# Control characters cannot be stored in a spreadsheet cell (XML forbids them),
# so they are refused at the door instead of blowing up in the renderer.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _reject_control_characters(value: str, *, code: str, subject: str) -> None:
    if _CONTROL_CHARS_RE.search(value):
        raise TimesheetError(
            code,
            f"{subject} contains invisible control characters, which cannot be written to a "
            "timesheet. Please retype it as plain text.",
            {"value": repr(value)},
        )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# field validators
# --------------------------------------------------------------------------


def validate_worker_id(raw: object) -> str:
    if not isinstance(raw, str) or _WORKER_ID_RE.fullmatch(raw) is None:
        raise TimesheetError(
            "invalid_worker_id",
            f"'{raw}' is not a valid worker ID. Use 1-32 characters: lowercase letters, "
            "digits, '-' or '_', starting with a letter or digit (for example 'anna-m').",
            {"value": raw, "pattern": WORKER_ID_PATTERN},
        )
    return raw


def validate_display_name(raw: object) -> str:
    if not isinstance(raw, str):
        raise TimesheetError("invalid_name", "The worker's name must be text.", {"value": repr(raw)})
    name = " ".join(raw.split())
    if not name:
        raise TimesheetError("invalid_name", "The worker's name must not be empty.", {"value": raw})
    if len(name) > MAX_NAME_LENGTH:
        raise TimesheetError(
            "invalid_name",
            f"The worker's name is too long (maximum {MAX_NAME_LENGTH} characters).",
            {"length": len(name)},
        )
    _reject_control_characters(name, code="invalid_name", subject="The worker's name")
    return name


def validate_currency(raw: object | None) -> str:
    """Currency is a plain label (spec R1) — it is never checked against a code list.

    Only surrounding whitespace is trimmed; the label is otherwise stored as
    typed, so 'Swiss francs (gross)' is as valid as 'CHF'.
    """
    if raw is None:
        return DEFAULT_CURRENCY
    if not isinstance(raw, str):
        raise TimesheetError("invalid_currency", "The currency label must be text.", {"value": repr(raw)})
    label = raw.strip()
    if not label:
        raise TimesheetError("invalid_currency", "The currency label must not be empty.", {"value": raw})
    _reject_control_characters(label, code="invalid_currency", subject="The currency label")
    return label


def validate_weekdays(raw: object) -> list[str]:
    if isinstance(raw, str):
        items: Iterable[Any] = [part for part in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        raise TimesheetError(
            "invalid_weekdays",
            "Working weekdays must be a list, for example 'mon,tue,wed'.",
            {"value": repr(raw)},
        )

    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TimesheetError(
                "invalid_weekdays",
                "Working weekdays must be text values such as 'mon'.",
                {"value": repr(item)},
            )
        token = item.strip().lower()
        if not token:
            continue
        if token not in _WEEKDAY_ORDER:
            raise TimesheetError(
                "invalid_weekdays",
                f"'{item}' is not a weekday. Use any of: {', '.join(WEEKDAYS)}.",
                {"value": item, "allowed": list(WEEKDAYS)},
            )
        if token not in normalized:
            normalized.append(token)
    return sorted(normalized, key=_WEEKDAY_ORDER.__getitem__)


def _validate_month_key(raw: object) -> str:
    return validate_month(raw)


def _validate_date_in_month(raw: object, month: str) -> str:
    if not isinstance(raw, str):
        raise TimesheetError("invalid_date", "Dates must be text in the form YYYY-MM-DD.", {"value": repr(raw)})
    value = raw.strip()
    try:
        if _DATE_RE.fullmatch(value) is None:
            raise ValueError("unexpected date shape")
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise TimesheetError(
            "invalid_date",
            f"'{raw}' is not a real date. Use the form YYYY-MM-DD, for example '2026-08-05'.",
            {"value": raw},
        ) from exc
    if parsed.strftime("%Y-%m") != month:
        raise TimesheetError(
            "date_outside_month",
            f"The date '{value}' does not belong to the month {month}.",
            {"value": value, "month": month},
        )
    return parsed.isoformat()


def validate_month_overrides(raw: object) -> dict[str, dict[str, list[str]]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TimesheetError(
            "invalid_overrides",
            "Month exceptions must be given per month, for example {'2026-08': {'off': ['2026-08-05']}}.",
            {"value": repr(raw)},
        )

    result: dict[str, dict[str, list[str]]] = {}
    for month_raw, entry in raw.items():
        month = _validate_month_key(month_raw)
        if not isinstance(entry, dict):
            raise TimesheetError(
                "invalid_overrides",
                f"The exceptions for {month} must list 'off' and/or 'extra' dates.",
                {"month": month, "value": repr(entry)},
            )
        unknown = set(entry) - {"off", "extra"}
        if unknown:
            raise TimesheetError(
                "invalid_overrides",
                f"Unknown exception type(s) for {month}: {', '.join(sorted(unknown))}. "
                "Only 'off' and 'extra' are supported.",
                {"month": month, "unknown": sorted(unknown)},
            )

        buckets: dict[str, list[str]] = {}
        for kind in ("off", "extra"):
            # Only an absent or explicitly null field means "no dates"; a
            # falsey value such as 0, false or {} is a malformed record.
            values = entry.get(kind)
            if values is None:
                values = []
            if isinstance(values, str):
                values = [part for part in values.split(",")]
            if not isinstance(values, (list, tuple)):
                raise TimesheetError(
                    "invalid_overrides",
                    f"The '{kind}' dates for {month} must be a list of dates.",
                    {"month": month, "value": repr(values)},
                )
            dates: list[str] = []
            for item in values:
                if isinstance(item, str) and not item.strip():
                    continue
                value = _validate_date_in_month(item, month)
                if value not in dates:
                    dates.append(value)
            buckets[kind] = sorted(dates)

        clash = sorted(set(buckets["off"]) & set(buckets["extra"]))
        if clash:
            raise TimesheetError(
                "override_conflict",
                f"These dates in {month} are marked both as day off and as extra working day: "
                f"{', '.join(clash)}. Please pick one.",
                {"month": month, "dates": clash},
            )

        if buckets["off"] or buckets["extra"]:
            result[month] = buckets
    return dict(sorted(result.items()))


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------


def build_record(
    *,
    worker_id: object,
    display_name: object,
    weekdays: object,
    rate: object,
    currency: object | None = None,
    month_overrides: object | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Validate raw field values into a canonical worker record."""
    record = {
        "id": validate_worker_id(worker_id),
        "display_name": validate_display_name(display_name),
        "working_weekdays": validate_weekdays(weekdays),
        "hourly_rate": canonical_decimal_string(parse_rate(rate)),
        "currency": validate_currency(currency),
        "month_overrides": validate_month_overrides(month_overrides),
        "created_at": created_at or _now(),
        "updated_at": updated_at or _now(),
    }
    return record


def record_warnings(record: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not record["working_weekdays"]:
        warnings.append(
            f"Worker '{record['id']}' has no regular working weekdays. Monthly sheets will show "
            "only the days you add as exceptions."
        )
    return warnings


def normalize_record(raw: object) -> dict[str, Any]:
    """Re-validate an externally supplied record (import path)."""
    if not isinstance(raw, dict):
        raise TimesheetError("invalid_record", "Each worker entry must be an object.", {"value": repr(raw)})
    missing = [key for key in ("id", "display_name", "working_weekdays", "hourly_rate") if key not in raw]
    if missing:
        raise TimesheetError(
            "invalid_record",
            f"A worker entry is missing required field(s): {', '.join(missing)}.",
            {"missing": missing, "id": raw.get("id")},
        )
    return build_record(
        worker_id=raw.get("id"),
        display_name=raw.get("display_name"),
        weekdays=raw.get("working_weekdays"),
        rate=raw.get("hourly_rate"),
        currency=raw.get("currency"),
        month_overrides=raw.get("month_overrides"),
        created_at=raw.get("created_at") if isinstance(raw.get("created_at"), str) else None,
        updated_at=_now(),
    )


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------


def load_registry(data_dir: DataDir) -> dict[str, Any]:
    path = data_dir.registry_path
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return {"version": REGISTRY_VERSION, "workers": {}}

    if not isinstance(payload, dict) or not isinstance(payload.get("workers"), dict):
        raise TimesheetError(
            "corrupt_registry",
            f"The worker file '{path}' is not in the expected format.",
            {"path": str(path)},
        )
    version = payload.get("version")
    if version != REGISTRY_VERSION:
        raise TimesheetError(
            "unsupported_registry_version",
            f"The worker file '{path}' was written by a different version "
            f"(found {version!r}, expected {REGISTRY_VERSION}).",
            {"path": str(path), "version": version},
        )
    return payload


def save_registry(data_dir: DataDir, registry: dict[str, Any]) -> None:
    payload = {
        "version": REGISTRY_VERSION,
        "workers": dict(sorted(registry.get("workers", {}).items())),
    }
    write_json_atomic(data_dir.registry_path, payload)


def get_worker(data_dir: DataDir, worker_id: str) -> dict[str, Any]:
    validated = validate_worker_id(worker_id)
    registry = load_registry(data_dir)
    record = registry["workers"].get(validated)
    if record is None:
        raise TimesheetError(
            "unknown_worker",
            f"No worker is registered with the ID '{validated}'. Use 'show' to list registered workers.",
            {"worker_id": validated},
        )
    return record


def list_workers(data_dir: DataDir) -> list[dict[str, Any]]:
    registry = load_registry(data_dir)
    return [registry["workers"][key] for key in sorted(registry["workers"])]


def register_worker(
    data_dir: DataDir,
    *,
    worker_id: object,
    display_name: object | None = None,
    weekdays: object | None = None,
    rate: object | None = None,
    currency: object | None = None,
    month_overrides: object | None = None,
    replace_overrides: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Create or update a worker.

    Month overrides survive a re-registration unless ``replace_overrides`` is
    set (plan decision 2); supplying exceptions for a month replaces just that
    month.
    """
    validated_id = validate_worker_id(worker_id)
    # The whole read-modify-write cycle is held under one lock, so two parallel
    # registrations cannot each read the old registry and drop the other's worker.
    with file_lock(data_dir.lock_path):
        return _register_locked(
            data_dir,
            validated_id,
            display_name=display_name,
            weekdays=weekdays,
            rate=rate,
            currency=currency,
            month_overrides=month_overrides,
            replace_overrides=replace_overrides,
        )


def _register_locked(
    data_dir: DataDir,
    validated_id: str,
    *,
    display_name: object | None,
    weekdays: object | None,
    rate: object | None,
    currency: object | None,
    month_overrides: object | None,
    replace_overrides: bool,
) -> tuple[dict[str, Any], list[str]]:
    registry = load_registry(data_dir)
    existing = registry["workers"].get(validated_id)

    if existing is None:
        missing = [
            label
            for label, value in (("--name", display_name), ("--weekdays", weekdays), ("--rate", rate))
            if value is None
        ]
        if missing:
            raise TimesheetError(
                "incomplete_registration",
                f"New worker '{validated_id}' needs {', '.join(missing)}.",
                {"worker_id": validated_id, "missing": missing},
            )
        overrides = validate_month_overrides(month_overrides)
        record = build_record(
            worker_id=validated_id,
            display_name=display_name,
            weekdays=weekdays,
            rate=rate,
            currency=currency,
            month_overrides=overrides,
        )
    else:
        incoming = validate_month_overrides(month_overrides)
        if replace_overrides:
            overrides = incoming
        else:
            overrides = dict(existing.get("month_overrides") or {})
            overrides.update(incoming)
            overrides = validate_month_overrides(overrides)
        record = build_record(
            worker_id=validated_id,
            display_name=existing["display_name"] if display_name is None else display_name,
            weekdays=existing["working_weekdays"] if weekdays is None else weekdays,
            rate=existing["hourly_rate"] if rate is None else rate,
            currency=existing["currency"] if currency is None else currency,
            month_overrides=overrides,
            created_at=existing.get("created_at"),
        )

    registry["workers"][validated_id] = record
    save_registry(data_dir, registry)
    return record, record_warnings(record)


# --------------------------------------------------------------------------
# export / import bundle (registry only — never sessions or photos)
# --------------------------------------------------------------------------


def export_bundle(data_dir: DataDir) -> dict[str, Any]:
    return {
        "bundle_version": BUNDLE_VERSION,
        "kind": BUNDLE_KIND,
        "exported_at": _now(),
        "workers": list_workers(data_dir),
    }


def import_bundle(data_dir: DataDir, bundle: object, *, force: bool = False) -> tuple[list[str], list[str]]:
    """Validate a whole bundle, then write it in one go.

    Nothing is written until every record has passed the registration
    validators; one bad record rejects the entire import.
    """
    if not isinstance(bundle, dict):
        raise TimesheetError("invalid_bundle", "The import file must contain a data bundle object.", None)

    version = bundle.get("bundle_version")
    if version != BUNDLE_VERSION:
        raise TimesheetError(
            "unsupported_bundle_version",
            f"This data file was written for version {version!r}, but this skill reads version "
            f"{BUNDLE_VERSION}.",
            {"bundle_version": version, "supported": BUNDLE_VERSION},
        )
    kind = bundle.get("kind")
    if kind != BUNDLE_KIND:
        raise TimesheetError(
            "invalid_bundle",
            f"This file is not an employee-timesheet worker bundle (found kind {kind!r}).",
            {"kind": kind},
        )

    workers = bundle.get("workers")
    if not isinstance(workers, list):
        raise TimesheetError("invalid_bundle", "The bundle's 'workers' entry must be a list.", None)

    validated: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for raw in workers:
        record = normalize_record(raw)
        if record["id"] in validated:
            raise TimesheetError(
                "duplicate_worker",
                f"The data file contains worker '{record['id']}' more than once.",
                {"worker_id": record["id"]},
            )
        validated[record["id"]] = record
        warnings.extend(record_warnings(record))

    # Read-modify-write under one lock, exactly like registration.
    with file_lock(data_dir.lock_path):
        registry = load_registry(data_dir)
        clobbered = sorted(set(validated) & set(registry["workers"]))
        if clobbered and not force:
            raise TimesheetError(
                "import_would_overwrite",
                "These workers are already registered here: "
                f"{', '.join(clobbered)}. Nothing was changed. Repeat with --force to overwrite them.",
                {"workers": clobbered},
            )

        registry["workers"].update(validated)
        save_registry(data_dir, registry)
    return sorted(validated), warnings
