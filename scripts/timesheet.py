#!/usr/bin/env python3
"""Employee timesheet skill — command line entry point.

Subcommands available so far::

    register       create or update a worker
    show           read a worker back (or list all)
    export-data    write a portable worker bundle (registry only)
    import-data    read a worker bundle back in, transactionally

Every subcommand accepts ``--json`` for machine-readable output. Failures print
``{"code", "message", "detail"}`` to stderr and exit non-zero; the ``message``
is written in plain language so it can be relayed to the user verbatim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import registry as reg  # noqa: E402
from lib.datadir import (  # noqa: E402
    DataDir,
    find_git_worktree,
    read_json,
    reserve_new_file,
    resolve_data_dir,
    write_json_atomic,
)
from lib.errors import TimesheetError  # noqa: E402

EXIT_ERROR = 1


# --------------------------------------------------------------------------
# argument helpers
# --------------------------------------------------------------------------


def _parse_override_args(values: list[str] | None, kind: str) -> dict[str, dict[str, list[str]]]:
    """Parse repeated ``--off 2026-08:2026-08-05,2026-08-06`` arguments."""
    overrides: dict[str, dict[str, list[str]]] = {}
    for raw in values or []:
        month, sep, dates = raw.partition(":")
        if not sep:
            raise TimesheetError(
                "invalid_overrides",
                f"'{raw}' is not a valid --{kind} value. Use MONTH:DATES, "
                f"for example --{kind} 2026-08:2026-08-05,2026-08-06.",
                {"value": raw},
            )
        bucket = overrides.setdefault(month.strip(), {"off": [], "extra": []})
        bucket[kind].extend(part.strip() for part in dates.split(",") if part.strip())
    return overrides


def _merge_override_args(off: list[str] | None, extra: list[str] | None) -> dict[str, Any] | None:
    parsed_off = _parse_override_args(off, "off")
    parsed_extra = _parse_override_args(extra, "extra")
    if not parsed_off and not parsed_extra:
        return None
    merged: dict[str, dict[str, list[str]]] = {}
    for source in (parsed_off, parsed_extra):
        for month, buckets in source.items():
            target = merged.setdefault(month, {"off": [], "extra": []})
            target["off"].extend(buckets["off"])
            target["extra"].extend(buckets["extra"])
    return merged


def _data_dir(args: argparse.Namespace) -> DataDir:
    return resolve_data_dir(args.data_dir, allow_repo_data=args.allow_repo_data)


def _resolve_outside_git(path: Path, allow_repo_data: bool) -> Path:
    """Refuse to write a worker bundle anywhere git could pick it up."""
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = (path.parent.resolve() / path.name) if path.parent.exists() else path.resolve()
    worktree = find_git_worktree(resolved.parent)
    if worktree is not None and not allow_repo_data:
        raise TimesheetError(
            "export_into_git_repo",
            f"'{resolved}' is inside the code folder '{worktree}', which is managed by git. "
            "Worker data must never land somewhere it could be committed. Please choose a "
            "folder outside this project, for example your home folder.",
            {"path": str(resolved), "git_worktree": str(worktree)},
        )
    return resolved


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------


def cmd_register(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    overrides = _merge_override_args(args.off, args.extra)
    record, warnings = reg.register_worker(
        data_dir,
        worker_id=args.worker,
        display_name=args.name,
        weekdays=args.weekdays,
        rate=args.rate,
        currency=args.currency,
        month_overrides=overrides,
        replace_overrides=args.replace_overrides,
    )
    return {
        "command": "register",
        "worker": record,
        "data_dir": str(data_dir.path),
        "warnings": data_dir.warnings + warnings,
    }


def cmd_show(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    if args.worker:
        payload: dict[str, Any] = {"command": "show", "worker": reg.get_worker(data_dir, args.worker)}
    else:
        payload = {"command": "show", "workers": reg.list_workers(data_dir)}
    payload["data_dir"] = str(data_dir.path)
    payload["warnings"] = list(data_dir.warnings)
    return payload


def cmd_export_data(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    bundle = reg.export_bundle(data_dir)
    output = _resolve_outside_git(Path(args.output).expanduser(), args.allow_repo_data)
    if not args.force:
        # Atomic claim: no window between checking and writing.
        reserve_new_file(output)
    write_json_atomic(output, bundle)
    return {
        "command": "export-data",
        "path": str(output),
        "worker_count": len(bundle["workers"]),
        "data_dir": str(data_dir.path),
        "warnings": list(data_dir.warnings),
    }


def cmd_import_data(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    source = Path(args.input).expanduser()
    try:
        bundle = read_json(source)
    except FileNotFoundError as exc:
        raise TimesheetError(
            "input_missing",
            f"The file '{source}' does not exist.",
            {"path": str(source)},
        ) from exc
    imported, warnings = reg.import_bundle(data_dir, bundle, force=args.force)
    return {
        "command": "import-data",
        "imported": imported,
        "worker_count": len(imported),
        "data_dir": str(data_dir.path),
        "warnings": data_dir.warnings + warnings,
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _render_human(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    command = payload.get("command")
    if command == "register":
        worker = payload["worker"]
        lines.append(f"Registered worker '{worker['id']}' ({worker['display_name']}).")
        lines.append(f"  Working weekdays: {', '.join(worker['working_weekdays']) or '(none)'}")
        lines.append(f"  Hourly rate:      {worker['hourly_rate']} {worker['currency']}")
        for month, buckets in worker["month_overrides"].items():
            lines.append(
                f"  {month}: off {', '.join(buckets['off']) or '-'} | extra {', '.join(buckets['extra']) or '-'}"
            )
    elif command == "show":
        workers = [payload["worker"]] if "worker" in payload else payload["workers"]
        if not workers:
            lines.append("No workers are registered yet.")
        for worker in workers:
            lines.append(
                f"{worker['id']}: {worker['display_name']} — {worker['hourly_rate']} {worker['currency']} "
                f"— {', '.join(worker['working_weekdays']) or 'no working weekdays'}"
            )
    elif command == "export-data":
        lines.append(f"Wrote {payload['worker_count']} worker(s) to {payload['path']}.")
    elif command == "import-data":
        lines.append(f"Imported {payload['worker_count']} worker(s): {', '.join(payload['imported']) or '-'}")

    for warning in payload.get("warnings", []):
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_render_human(payload))


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


class StructuredArgumentParser(argparse.ArgumentParser):
    """argparse that reports usage problems through the JSON error contract."""

    def error(self, message: str) -> Any:  # type: ignore[override]
        raise TimesheetError(
            "invalid_arguments",
            f"{message.capitalize()}. Run '{self.prog} --help' to see the available options.",
            {"usage": self.format_usage().strip()},
        )


def build_parser() -> argparse.ArgumentParser:
    parser = StructuredArgumentParser(
        prog="timesheet",
        description="Generate and evaluate monthly employee timesheets.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--data-dir", help="Folder for local worker data (default: ~/.employee-timesheet).")
        sub.add_argument("--allow-repo-data", action="store_true", help=argparse.SUPPRESS)
        sub.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    register = subparsers.add_parser("register", help="Create or update a worker.")
    register.add_argument("--worker", required=True, help="Stable worker ID, e.g. 'anna-m'.")
    register.add_argument("--name", help="Display name shown on the sheet.")
    register.add_argument("--weekdays", help="Regular working weekdays, e.g. 'mon,tue,wed'.")
    register.add_argument("--rate", help="Gross hourly rate, e.g. '7.50' or '7,50'.")
    register.add_argument("--currency", help="Currency label attached to amounts (default: CHF).")
    register.add_argument(
        "--off", action="append", metavar="MONTH:DATES", help="Extra days off, e.g. 2026-08:2026-08-05."
    )
    register.add_argument(
        "--extra", action="append", metavar="MONTH:DATES", help="Exceptional working days, e.g. 2026-08:2026-08-09."
    )
    register.add_argument(
        "--replace-overrides",
        action="store_true",
        help="Replace all stored month exceptions instead of keeping the existing ones.",
    )
    add_common(register)
    register.set_defaults(func=cmd_register)

    show = subparsers.add_parser("show", help="Show one worker, or list all registered workers.")
    show.add_argument("--worker", help="Worker ID; omit to list every registered worker.")
    add_common(show)
    show.set_defaults(func=cmd_show)

    export = subparsers.add_parser(
        "export-data", help="Write a portable bundle of the worker registry (no photos, no sessions)."
    )
    export.add_argument("--output", required=True, help="Destination file for the bundle JSON.")
    export.add_argument("--force", action="store_true", help="Overwrite the destination file if it exists.")
    add_common(export)
    export.set_defaults(func=cmd_export_data)

    imp = subparsers.add_parser("import-data", help="Read a worker bundle back into the local registry.")
    imp.add_argument("--input", required=True, help="Bundle JSON file to import.")
    imp.add_argument("--force", action="store_true", help="Overwrite workers that are already registered.")
    add_common(imp)
    imp.set_defaults(func=cmd_import_data)

    return parser


def main(argv: list[str] | None = None) -> int:
    as_json = True
    try:
        args = build_parser().parse_args(argv)
        as_json = bool(getattr(args, "json", False))
        payload = args.func(args)
    except TimesheetError as error:
        print(json.dumps(error.to_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    except OSError as error:
        failure = TimesheetError(
            "io_error",
            f"A file could not be read or written: {error.strerror or error}.",
            {"filename": getattr(error, "filename", None)},
        )
        print(json.dumps(failure.to_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    _emit(payload, as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
