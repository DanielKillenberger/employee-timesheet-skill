#!/usr/bin/env python3
"""Employee timesheet skill — command line entry point.

Subcommands available so far::

    register             create or update a worker
    show                 read a worker back (or list all)
    generate             write the blank monthly sheet for a worker (XLSX + PDF)
    validate-extraction  check transcribed hours and open a confirmation session
    confirm              correct/accept flagged days and freeze the month
    tally                produce the final tally for a confirmed month
    export-data          write a portable worker bundle (registry only)
    import-data          read a worker bundle back in, transactionally

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

from lib import extraction as ex  # noqa: E402
from lib import registry as reg  # noqa: E402
from lib.datadir import (  # noqa: E402
    DataDir,
    atomic_output_files,
    file_lock,
    find_git_worktree,
    read_json,
    reserve_new_file,
    resolve_data_dir,
    write_json_atomic,
)
from lib.errors import TimesheetError  # noqa: E402
from lib.layout import build_month_layout  # noqa: E402
from lib.money import canonical_decimal_string  # noqa: E402
from lib.pdf_sheet import render_month_pdf, sheet_pdf_filename  # noqa: E402
from lib.tally import generate_tally  # noqa: E402
from lib.xlsx_sheet import render_month_sheet, sheet_filename  # noqa: E402

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


def cmd_generate(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    record = reg.get_worker(data_dir, args.worker)
    layout = build_month_layout(record, args.month)

    xlsx_target = data_dir.output_dir / sheet_filename(layout)
    pdf_target = data_dir.output_dir / sheet_pdf_filename(layout)
    claimed: list[Path] = []
    if not args.force:
        # Atomic claim of both documents, so a sheet someone already filled in
        # is never silently replaced by a fresh blank one — and so the run fails
        # before writing anything rather than half way through. If the second
        # claim fails, the first is released again: an abandoned empty file
        # would make the next run fail for the wrong reason.
        try:
            for target in (xlsx_target, pdf_target):
                reserve_new_file(target)
                claimed.append(target)
        except BaseException:
            for target in claimed:
                target.unlink(missing_ok=True)
            raise
    try:
        # Both documents are rendered before either replaces its target, so a
        # failure never leaves a fresh spreadsheet next to last month's PDF.
        with atomic_output_files([xlsx_target, pdf_target]) as (staged_xlsx, staged_pdf):
            written = render_month_sheet(
                layout,
                staged_xlsx,
                include_rate=args.include_rate,
                hourly_rate=record["hourly_rate"],
                currency=record["currency"],
            )
            render_month_pdf(
                layout,
                staged_pdf,
                include_rate=args.include_rate,
                hourly_rate=record["hourly_rate"],
                currency=record["currency"],
            )
    except BaseException:
        for target in claimed:
            target.unlink(missing_ok=True)  # drop the empty claims
        raise

    warnings = list(data_dir.warnings)
    if not layout.working_rows:
        warnings.append(
            f"The sheet for {layout.title} has no working days at all. Check the worker's "
            "weekdays and month exceptions."
        )
    return {
        "command": "generate",
        "worker": {"id": layout.worker_id, "display_name": layout.display_name},
        "month": layout.month,
        "month_title": layout.title,
        # The published targets, not the staging paths the renderers saw.
        "files": {"xlsx": str(xlsx_target), "pdf": str(pdf_target)},
        "days": written["rows"],
        "working_days": written["working_days"],
        "off_days": written["off_days"],
        "rate_printed": bool(args.include_rate),
        "data_dir": str(data_dir.path),
        "warnings": warnings,
    }


def _read_entries_document(source: str) -> Any:
    """Read the transcription document from a file or from stdin (``-``)."""
    if source == "-":
        text = sys.stdin.read()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise TimesheetError(
                "corrupt_json",
                f"The entries given on standard input are not readable as JSON "
                f"({exc.msg}, line {exc.lineno}).",
                {"source": "stdin"},
            ) from exc
    path = Path(source).expanduser()
    try:
        return read_json(path)
    except FileNotFoundError as exc:
        raise TimesheetError(
            "input_missing",
            f"The entries file '{path}' does not exist.",
            {"path": str(path)},
        ) from exc


def cmd_validate_extraction(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    record = reg.get_worker(data_dir, args.worker)
    layout = build_month_layout(record, args.month)
    document = ex.parse_entries_document(
        _read_entries_document(args.entries), layout=layout, worker_id=record["id"]
    )

    # One lock for the whole check-then-write cycle: two parallel extractions
    # for the same month must not both decide the session does not exist yet.
    with file_lock(data_dir.session_lock_path):
        path = ex.session_path(data_dir, record["id"], layout.month)
        if path.exists() and not args.overwrite:
            raise TimesheetError(
                "session_exists",
                f"An extraction for {layout.title} already exists for worker '{record['id']}'. "
                "Nothing was changed. Use 'confirm' to continue it, or repeat with --overwrite "
                "to start the transcription again.",
                {"worker_id": record["id"], "month": layout.month, "path": str(path)},
            )
        evidence = ex.ingest_evidence(data_dir, args.photo or [], worker_id=record["id"], month=layout.month)
        session = ex.build_session(record=record, layout=layout, document=document, evidence=evidence)
        session_file = ex.save_session(data_dir, session)

    attention = ex.attention_items(session)
    identity = session["identity"]
    warnings = list(data_dir.warnings)
    if identity["status"] in ex.IDENTITY_BLOCKING:
        warnings.append(
            "The worker name on the sheet "
            + (
                "does not match the registered name"
                if identity["status"] == ex.IDENTITY_MISMATCH
                else "could not be read"
            )
            + f" (registered: '{identity['registered_name']}'). Confirmation needs --accept-identity."
        )
    return {
        "command": "validate-extraction",
        "worker": {"id": record["id"], "display_name": record["display_name"]},
        "month": layout.month,
        "month_title": layout.title,
        "status": session["status"],
        "provisional_total_hours": canonical_decimal_string(ex.provisional_total(session)),
        "days": len(session["days"]),
        "identity": {
            "status": identity["status"],
            "observed_name": identity["observed_name"],
            "registered_name": identity["registered_name"],
        },
        "extraction_report": ex.extraction_report(session),
        "needs_attention": attention,
        "needs_attention_count": len(attention),
        "evidence": session["evidence"],
        "session_file": str(session_file),
        "data_dir": str(data_dir.path),
        "warnings": warnings,
    }


def cmd_confirm(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    corrections = [ex.parse_set_argument(raw) for raw in (args.set or [])]

    with file_lock(data_dir.session_lock_path):
        session = ex.load_session(data_dir, args.worker, args.month)
        if session["status"] == ex.STATUS_CONFIRMED:
            if corrections or args.accept_identity:
                raise TimesheetError(
                    "already_confirmed",
                    f"The hours for {session.get('month_title', session['month'])} were already confirmed on "
                    f"{session['confirmation']['confirmed_at']} and cannot be changed. To start over, "
                    "run 'validate-extraction' again with --overwrite.",
                    {"worker_id": session["worker_id"], "month": session["month"]},
                )
            confirmation = session["confirmation"]
            session_file = ex.session_path(data_dir, session["worker_id"], session["month"])
        else:
            record = reg.get_worker(data_dir, session["worker_id"])
            for iso, hours in corrections:
                ex.apply_correction(session, iso, hours)
            try:
                confirmation = ex.confirm_session(session, record, accept_identity=args.accept_identity)
            except TimesheetError:
                # Keep the corrections that did land, so a long month can be
                # worked through in several passes.
                ex.save_session(data_dir, session)
                raise
            session_file = ex.save_session(data_dir, session)

    return {
        "command": "confirm",
        "worker": {
            "id": confirmation["snapshot"]["worker_id"],
            "display_name": confirmation["snapshot"]["display_name"],
        },
        "month": session["month"],
        "month_title": session.get("month_title", session["month"]),
        "status": session["status"],
        "confirmed_at": confirmation["confirmed_at"],
        "total_hours": confirmation["total_hours"],
        "receipt": confirmation["receipt"],
        "snapshot": confirmation["snapshot"],
        "days": confirmation["days"],
        "identity": {
            "status": session["identity"]["status"],
            "accepted": session["identity"]["accepted"],
        },
        "session_file": str(session_file),
        "data_dir": str(data_dir.path),
        "warnings": list(data_dir.warnings),
    }


def cmd_tally(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = _data_dir(args)
    result = generate_tally(
        data_dir,
        worker_id=args.worker,
        month=args.month,
        template=args.template,
        # Without --force every output file is claimed first, so an existing
        # tally is reported instead of quietly replaced.
        reserve=None if args.force else reserve_new_file,
    )
    return {
        "command": "tally",
        **result,
        "data_dir": str(data_dir.path),
        "warnings": data_dir.warnings + result["notes"],
    }


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
    elif command == "generate":
        lines.append(
            f"Wrote the timesheet for {payload['worker']['display_name']} ({payload['month_title']})."
        )
        lines.append(f"  Excel: {payload['files']['xlsx']}")
        lines.append(f"  PDF:   {payload['files']['pdf']}")
        lines.append(
            f"  {payload['days']} days — {payload['working_days']} working, {payload['off_days']} off."
        )
    elif command == "validate-extraction":
        lines.append(
            f"Checked the hours for {payload['worker']['display_name']} ({payload['month_title']})."
        )
        lines.append(f"  Provisional total (readable days only): {payload['provisional_total_hours']} h")
        lines.append(f"  Name on the sheet: {payload['identity']['status']}")
        if payload["needs_attention"]:
            lines.append(f"  {payload['needs_attention_count']} day(s) need a decision:")
            for item in payload["needs_attention"]:
                lines.append(f"    {item['label']}: {', '.join(item['reasons'])} — {item['resolution']}")
        else:
            lines.append("  No days need a decision; you can run 'confirm'.")
        for item in payload["evidence"]:
            lines.append(f"  Photo kept as {item['stored_filename']} (sha256 {item['sha256'][:12]}…)")
    elif command == "confirm":
        lines.append(
            f"Confirmed {payload['total_hours']} hours for {payload['worker']['display_name']} "
            f"({payload['month_title']})."
        )
        lines.append(f"  {payload['receipt']['statement']}")
    elif command == "tally":
        lines.append(
            f"Final tally for {payload['worker']['display_name']} ({payload['month_title']}), "
            f"generated {payload['generation_date']}."
        )
        lines.append(f"  {payload['calculation']}")
        lines.append(f"  PDF:   {payload['files']['pdf']}")
        lines.append(f"  Excel: {payload['files']['xlsx']} (template: {payload['template']['source']})")
        if payload["files"]["templated_pdf"]:
            lines.append(f"  PDF from the template: {payload['files']['templated_pdf']}")
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

    generate = subparsers.add_parser("generate", help="Write the blank monthly sheet for a worker.")
    generate.add_argument("--worker", required=True, help="Registered worker ID.")
    generate.add_argument("--month", required=True, help="Month to generate, e.g. '2026-08'.")
    generate.add_argument(
        "--include-rate",
        action="store_true",
        help="Print the hourly rate on the sheet (left off by default).",
    )
    generate.add_argument("--force", action="store_true", help="Replace an existing sheet for this month.")
    add_common(generate)
    generate.set_defaults(func=cmd_generate)

    validate = subparsers.add_parser(
        "validate-extraction",
        help="Check transcribed hours against the month and open a confirmation session.",
    )
    validate.add_argument("--worker", required=True, help="Registered worker ID (never guessed from the sheet).")
    validate.add_argument("--month", required=True, help="Month the sheet covers, e.g. '2026-08'.")
    validate.add_argument(
        "--entries",
        required=True,
        metavar="PATH",
        help="JSON file with the transcribed days, or '-' to read it from standard input.",
    )
    validate.add_argument(
        "--photo",
        action="append",
        metavar="PATH",
        help="Photo/scan of the filled-in sheet, kept as evidence (repeatable).",
    )
    validate.add_argument(
        "--overwrite", action="store_true", help="Replace an existing extraction for this month."
    )
    add_common(validate)
    validate.set_defaults(func=cmd_validate_extraction)

    confirm = subparsers.add_parser(
        "confirm", help="Correct or accept flagged days and freeze the month's hours."
    )
    confirm.add_argument("--worker", required=True, help="Registered worker ID.")
    confirm.add_argument("--month", required=True, help="Month to confirm, e.g. '2026-08'.")
    confirm.add_argument(
        "--set",
        action="append",
        metavar="DATE=HOURS",
        help="Correct one day, e.g. --set 2026-08-04=7.5 (repeat the shown value to accept it).",
    )
    confirm.add_argument(
        "--accept-identity",
        action="store_true",
        help="Confirm the sheet belongs to this worker although the name did not match or was unreadable.",
    )
    add_common(confirm)
    confirm.set_defaults(func=cmd_confirm)

    tally = subparsers.add_parser(
        "tally", help="Produce the final tally documents for a confirmed month."
    )
    tally.add_argument("--worker", required=True, help="Registered worker ID.")
    tally.add_argument("--month", required=True, help="Confirmed month, e.g. '2026-08'.")
    tally.add_argument(
        "--template",
        metavar="PATH",
        help="XLSX template for the tally (default: templates/tally.xlsx in the data folder, "
        "otherwise the built-in one).",
    )
    tally.add_argument("--force", action="store_true", help="Replace existing tally documents.")
    add_common(tally)
    tally.set_defaults(func=cmd_tally)

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
