"""Worker registry: validation, round-trip, overrides, data-dir safety, bundles."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import timesheet
from lib import registry as reg
from lib.datadir import (
    ENV_VAR,
    ensure_private_dir,
    file_lock,
    reserve_new_file,
    resolve_data_dir,
    safe_child,
    write_json_atomic,
)
from lib.errors import TimesheetError

SCRIPTS_DIR = Path(timesheet.__file__).resolve().parent


@pytest.fixture()
def data_dir(tmp_path: Path):
    return resolve_data_dir(str(tmp_path / "data"))


def register_anna(data_dir, **overrides):
    kwargs = {
        "worker_id": "anna",
        "display_name": "Anna Muster",
        "weekdays": "mon,tue,wed",
        "rate": "7,50",
    }
    kwargs.update(overrides)
    return reg.register_worker(data_dir, **kwargs)


# --------------------------------------------------------------------------
# AC1 — round-trip
# --------------------------------------------------------------------------


def test_register_and_read_back_preserves_rate_scale(data_dir) -> None:
    register_anna(data_dir)
    record = reg.get_worker(data_dir, "anna")
    assert record["display_name"] == "Anna Muster"
    assert record["working_weekdays"] == ["mon", "tue", "wed"]
    assert record["hourly_rate"] == "7.50"  # canonical dot notation, scale preserved
    assert record["currency"] == "CHF"


def test_weekdays_are_normalized_and_ordered(data_dir) -> None:
    record, _ = register_anna(data_dir, weekdays=" WED , mon,mon , fri ")
    assert record["working_weekdays"] == ["mon", "wed", "fri"]


def test_registry_file_is_owner_only(data_dir) -> None:
    register_anna(data_dir)
    assert (data_dir.registry_path.stat().st_mode & 0o777) == 0o600
    assert (data_dir.path.stat().st_mode & 0o777) == 0o700


def test_unknown_worker_error(data_dir) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.get_worker(data_dir, "nobody")
    assert excinfo.value.code == "unknown_worker"


# --------------------------------------------------------------------------
# ID grammar + path safety
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "worker_id",
    ["Anna", "../evil", "a/b", "..", "", "-anna", "_anna", "anna!", "a" * 33, "anna m", ".hidden"],
)
def test_invalid_worker_ids_rejected(worker_id: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.validate_worker_id(worker_id)
    assert excinfo.value.code == "invalid_worker_id"


@pytest.mark.parametrize("worker_id", ["a", "anna", "anna-m", "anna_m", "0", "a" * 32])
def test_valid_worker_ids_accepted(worker_id: str) -> None:
    assert reg.validate_worker_id(worker_id) == worker_id


@pytest.mark.parametrize("part", ["..", "../escape", "/etc/passwd", "sub/dir", "", "."])
def test_safe_child_refuses_escapes(tmp_path: Path, part: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        safe_child(tmp_path, part)
    assert excinfo.value.code == "unsafe_path"


def test_safe_child_stays_inside(data_dir) -> None:
    assert data_dir.child("employees.json").parent == data_dir.path


# --------------------------------------------------------------------------
# overrides (plan decisions 2, 3, 5)
# --------------------------------------------------------------------------


def test_overrides_preserved_on_re_registration(data_dir) -> None:
    register_anna(data_dir, month_overrides={"2026-08": {"off": ["2026-08-05"]}})
    record, _ = reg.register_worker(data_dir, worker_id="anna", rate="8,00")
    assert record["hourly_rate"] == "8.00"
    assert record["month_overrides"]["2026-08"]["off"] == ["2026-08-05"]


def test_replace_overrides_clears_stored_exceptions(data_dir) -> None:
    register_anna(data_dir, month_overrides={"2026-08": {"off": ["2026-08-05"]}})
    record, _ = reg.register_worker(data_dir, worker_id="anna", replace_overrides=True)
    assert record["month_overrides"] == {}


def test_supplying_a_month_replaces_only_that_month(data_dir) -> None:
    register_anna(
        data_dir,
        month_overrides={"2026-08": {"off": ["2026-08-05"]}, "2026-09": {"extra": ["2026-09-12"]}},
    )
    record, _ = reg.register_worker(
        data_dir, worker_id="anna", month_overrides={"2026-08": {"off": ["2026-08-06"]}}
    )
    assert record["month_overrides"]["2026-08"]["off"] == ["2026-08-06"]
    assert record["month_overrides"]["2026-09"]["extra"] == ["2026-09-12"]


def test_same_date_off_and_extra_is_an_error(data_dir) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        register_anna(data_dir, month_overrides={"2026-08": {"off": ["2026-08-05"], "extra": ["2026-08-05"]}})
    assert excinfo.value.code == "override_conflict"


def test_override_date_outside_its_month_rejected(data_dir) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        register_anna(data_dir, month_overrides={"2026-08": {"off": ["2026-09-01"]}})
    assert excinfo.value.code == "date_outside_month"


def test_leap_day_accepted_only_in_leap_years(data_dir) -> None:
    record, _ = register_anna(data_dir, month_overrides={"2024-02": {"off": ["2024-02-29"]}})
    assert record["month_overrides"]["2024-02"]["off"] == ["2024-02-29"]

    with pytest.raises(TimesheetError) as excinfo:
        reg.validate_month_overrides({"2023-02": {"off": ["2023-02-29"]}})
    assert excinfo.value.code == "invalid_date"


@pytest.mark.parametrize("month", ["2026-13", "26-08", "2026-8", "2026-00", "august"])
def test_invalid_month_keys_rejected(month: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.validate_month_overrides({month: {"off": []}})
    assert excinfo.value.code == "invalid_month"


@pytest.mark.parametrize("value", ["20260805", "2026-W32-3", "2026-8-5", "2026-08-05T00:00", " 2026-08-05 x"])
def test_only_exact_iso_dates_accepted(value: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.validate_month_overrides({"2026-08": {"off": [value]}})
    assert excinfo.value.code in {"invalid_date", "date_outside_month"}


@pytest.mark.parametrize("value", [False, 0, {}, {"2026-08-05": True}, 5])
def test_falsey_override_values_are_rejected(value: object) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.validate_month_overrides({"2026-08": {"off": value}})
    assert excinfo.value.code == "invalid_overrides"


def test_absent_or_null_override_field_means_no_dates() -> None:
    assert reg.validate_month_overrides({"2026-08": {"off": None, "extra": ["2026-08-09"]}}) == {
        "2026-08": {"off": [], "extra": ["2026-08-09"]}
    }


@pytest.mark.parametrize("label", ["CHF", "Swiss francs (gross)", "€", "brutto CHF / Stunde"])
def test_currency_is_a_plain_label(data_dir, label: str) -> None:
    record, _ = register_anna(data_dir, currency=label)
    assert record["currency"] == label


def test_currency_must_not_be_empty(data_dir) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        register_anna(data_dir, currency="   ")
    assert excinfo.value.code == "invalid_currency"


def test_zero_working_days_allowed_with_warning(data_dir) -> None:
    record, warnings = register_anna(data_dir, weekdays="")
    assert record["working_weekdays"] == []
    assert any("no regular working weekdays" in warning for warning in warnings)


def test_invalid_weekday_rejected(data_dir) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        register_anna(data_dir, weekdays="mon,funday")
    assert excinfo.value.code == "invalid_weekdays"


def test_new_worker_requires_name_weekdays_and_rate(data_dir) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.register_worker(data_dir, worker_id="anna", display_name="Anna")
    assert excinfo.value.code == "incomplete_registration"
    assert set(excinfo.value.detail["missing"]) == {"--weekdays", "--rate"}


# --------------------------------------------------------------------------
# data directory resolution
# --------------------------------------------------------------------------


def test_data_dir_precedence(tmp_path: Path) -> None:
    cli = tmp_path / "cli"
    env = {ENV_VAR: str(tmp_path / "env")}
    assert resolve_data_dir(str(cli), env=env).path == cli.resolve()
    assert resolve_data_dir(None, env=env).path == (tmp_path / "env").resolve()
    assert resolve_data_dir(None, env={}, create=False).source == "default"


def test_data_dir_inside_git_worktree_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(TimesheetError) as excinfo:
        resolve_data_dir(str(repo / "data"))
    assert excinfo.value.code == "data_dir_in_git_repo"
    assert not (repo / "data").exists()  # refused before creating anything

    allowed = resolve_data_dir(str(repo / "data"), allow_repo_data=True)
    assert allowed.path == (repo / "data").resolve()


def test_ephemeral_data_dir_warns() -> None:
    resolved = resolve_data_dir("/tmp/employee-timesheet-test", create=False)
    assert any("temporary location" in warning for warning in resolved.warnings)
    assert not (Path("/tmp") / "employee-timesheet-test").exists()  # create=False touched nothing


def test_persistent_data_dir_does_not_warn(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("lib.datadir._ephemeral_roots", lambda: [Path("/nowhere-ephemeral")])
    assert resolve_data_dir(str(tmp_path / "kept")).warnings == []


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "bundle.json"
    write_json_atomic(target, {"hello": "world"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "world"}
    assert [p.name for p in tmp_path.iterdir()] == ["bundle.json"]


def test_atomic_write_never_touches_an_existing_directory(tmp_path: Path) -> None:
    """Writing a file must not narrow the permissions of a folder we do not own."""
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    before = shared.stat().st_mode & 0o777
    write_json_atomic(shared / "bundle.json", {"hello": "world"})
    assert (shared.stat().st_mode & 0o777) == before
    assert (shared / "bundle.json").stat().st_mode & 0o777 == 0o600


def test_atomic_write_requires_an_existing_folder(tmp_path: Path) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        write_json_atomic(tmp_path / "missing" / "bundle.json", {})
    assert excinfo.value.code == "output_dir_missing"


def test_ensure_private_dir_creates_owner_only_without_touching_parents(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o755)
    before = parent.stat().st_mode & 0o777
    ensure_private_dir(parent / "data")
    assert (parent / "data").stat().st_mode & 0o777 == 0o700
    assert (parent.stat().st_mode & 0o777) == before


def test_reserve_new_file_is_exclusive(tmp_path: Path) -> None:
    target = tmp_path / "bundle.json"
    reserve_new_file(target)
    with pytest.raises(TimesheetError) as excinfo:
        reserve_new_file(target)
    assert excinfo.value.code == "output_exists"


# --------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS_DIR)
    return env


def test_registry_lock_is_exclusive_across_processes(data_dir) -> None:
    probe = (
        "import sys; sys.path.insert(0, %r);"
        "from lib.datadir import file_lock; from lib.errors import TimesheetError;"
        "from pathlib import Path;"
        "\ntry:\n"
        "    ctx = file_lock(Path(sys.argv[1]), blocking=False)\n"
        "    ctx.__enter__(); ctx.__exit__(None, None, None); print('acquired')\n"
        "except TimesheetError as error:\n"
        "    print(error.code)\n"
    ) % str(SCRIPTS_DIR)

    with file_lock(data_dir.lock_path):
        held = subprocess.run(
            [sys.executable, "-c", probe, str(data_dir.lock_path)],
            capture_output=True, text=True, check=True,
        )
    free = subprocess.run(
        [sys.executable, "-c", probe, str(data_dir.lock_path)],
        capture_output=True, text=True, check=True,
    )
    assert held.stdout.strip() == "data_dir_busy"
    assert free.stdout.strip() == "acquired"


def test_parallel_registrations_do_not_lose_workers(tmp_path: Path) -> None:
    """Without a lock the last writer would overwrite the others' records."""
    home = tmp_path / "home"
    ids = [f"w{index}" for index in range(8)]

    def register(worker_id: str) -> int:
        return subprocess.run(
            [
                sys.executable, str(SCRIPTS_DIR / "timesheet.py"),
                "register", "--worker", worker_id, "--name", f"Worker {worker_id}",
                "--weekdays", "mon", "--rate", "7.50",
                "--data-dir", str(home), "--json",
            ],
            capture_output=True, text=True, env=_cli_env(),
        ).returncode

    with ThreadPoolExecutor(max_workers=len(ids)) as pool:
        assert list(pool.map(register, ids)) == [0] * len(ids)

    stored = resolve_data_dir(str(home))
    assert [worker["id"] for worker in reg.list_workers(stored)] == sorted(ids)


def test_corrupt_registry_reports_clearly(data_dir) -> None:
    data_dir.registry_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TimesheetError) as excinfo:
        reg.load_registry(data_dir)
    assert excinfo.value.code == "corrupt_json"


def test_unsupported_registry_version(data_dir) -> None:
    write_json_atomic(data_dir.registry_path, {"version": 99, "workers": {}})
    with pytest.raises(TimesheetError) as excinfo:
        reg.load_registry(data_dir)
    assert excinfo.value.code == "unsupported_registry_version"


# --------------------------------------------------------------------------
# export / import bundle
# --------------------------------------------------------------------------


def test_bundle_round_trip(tmp_path: Path, data_dir) -> None:
    register_anna(data_dir, month_overrides={"2026-08": {"off": ["2026-08-05"]}})
    bundle = reg.export_bundle(data_dir)
    assert bundle["bundle_version"] == reg.BUNDLE_VERSION
    assert [worker["id"] for worker in bundle["workers"]] == ["anna"]

    target = resolve_data_dir(str(tmp_path / "other"))
    imported, _ = reg.import_bundle(target, bundle)
    assert imported == ["anna"]
    restored = reg.get_worker(target, "anna")
    assert restored["hourly_rate"] == "7.50"
    assert restored["month_overrides"]["2026-08"]["off"] == ["2026-08-05"]


def test_bundle_contains_no_absolute_paths_or_sessions(data_dir) -> None:
    register_anna(data_dir)
    serialized = json.dumps(reg.export_bundle(data_dir))
    assert str(data_dir.path) not in serialized
    assert "extractions" not in serialized
    assert "filled-timesheets" not in serialized


def test_import_refuses_to_clobber_without_force(data_dir) -> None:
    register_anna(data_dir)
    bundle = reg.export_bundle(data_dir)
    bundle["workers"][0]["display_name"] = "Someone Else"

    with pytest.raises(TimesheetError) as excinfo:
        reg.import_bundle(data_dir, bundle)
    assert excinfo.value.code == "import_would_overwrite"
    assert reg.get_worker(data_dir, "anna")["display_name"] == "Anna Muster"

    reg.import_bundle(data_dir, bundle, force=True)
    assert reg.get_worker(data_dir, "anna")["display_name"] == "Someone Else"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"id": "Anna"}, "invalid_worker_id"),
        ({"id": "../evil"}, "invalid_worker_id"),
        ({"hourly_rate": "7,5,0"}, "invalid_rate"),
        ({"hourly_rate": 7.5}, "invalid_rate"),
        ({"working_weekdays": ["funday"]}, "invalid_weekdays"),
        ({"display_name": ""}, "invalid_name"),
        ({"month_overrides": {"2023-02": {"off": ["2023-02-29"]}}}, "invalid_date"),
        ({"month_overrides": {"2026-08": {"off": ["2026-09-01"]}}}, "date_outside_month"),
        ({"month_overrides": {"2026-08": {"off": ["2026-08-05"], "extra": ["2026-08-05"]}}}, "override_conflict"),
    ],
)
def test_import_is_transactional(data_dir, tmp_path: Path, mutation: dict, code: str) -> None:
    """One bad record rejects the whole bundle — nothing is written."""
    source = resolve_data_dir(str(tmp_path / "source"))
    register_anna(source)
    reg.register_worker(source, worker_id="bob", display_name="Bob", weekdays="thu", rate="9,00")
    bundle = reg.export_bundle(source)
    bundle["workers"][1].update(mutation)

    with pytest.raises(TimesheetError) as excinfo:
        reg.import_bundle(data_dir, bundle)
    assert excinfo.value.code == code
    assert reg.list_workers(data_dir) == []  # the valid first record was not written either


def test_import_rejects_duplicate_ids(data_dir, tmp_path: Path) -> None:
    source = resolve_data_dir(str(tmp_path / "source"))
    register_anna(source)
    bundle = reg.export_bundle(source)
    bundle["workers"].append(dict(bundle["workers"][0]))
    with pytest.raises(TimesheetError) as excinfo:
        reg.import_bundle(data_dir, bundle)
    assert excinfo.value.code == "duplicate_worker"


@pytest.mark.parametrize(
    ("bundle", "code"),
    [
        ({"bundle_version": 99, "kind": reg.BUNDLE_KIND, "workers": []}, "unsupported_bundle_version"),
        ({"kind": reg.BUNDLE_KIND, "workers": []}, "unsupported_bundle_version"),
        ({"bundle_version": reg.BUNDLE_VERSION, "kind": "something-else", "workers": []}, "invalid_bundle"),
        ({"bundle_version": reg.BUNDLE_VERSION, "kind": reg.BUNDLE_KIND, "workers": {}}, "invalid_bundle"),
        ([], "invalid_bundle"),
    ],
)
def test_import_rejects_bad_bundles(data_dir, bundle: object, code: str) -> None:
    with pytest.raises(TimesheetError) as excinfo:
        reg.import_bundle(data_dir, bundle)
    assert excinfo.value.code == code


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def run_cli(*argv: str) -> int:
    return timesheet.main(list(argv))


def test_cli_help_works(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        timesheet.main(["--help"])
    assert excinfo.value.code == 0
    assert "register" in capsys.readouterr().out


def test_cli_register_show_export_import(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    other = tmp_path / "other"
    bundle_path = tmp_path / "workers.json"

    assert (
        run_cli(
            "register",
            "--worker", "anna",
            "--name", "Anna Muster",
            "--weekdays", "mon,tue,wed",
            "--rate", "7,50",
            "--off", "2026-08:2026-08-05,2026-08-06",
            "--extra", "2026-08:2026-08-09",
            "--data-dir", str(home),
            "--json",
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["worker"]["hourly_rate"] == "7.50"
    assert payload["worker"]["month_overrides"]["2026-08"] == {
        "off": ["2026-08-05", "2026-08-06"],
        "extra": ["2026-08-09"],
    }

    assert run_cli("export-data", "--output", str(bundle_path), "--data-dir", str(home), "--json") == 0
    capsys.readouterr()

    assert run_cli("import-data", "--input", str(bundle_path), "--data-dir", str(other), "--json") == 0
    capsys.readouterr()

    assert run_cli("show", "--worker", "anna", "--data-dir", str(other), "--json") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["worker"]["display_name"] == "Anna Muster"
    assert shown["worker"]["hourly_rate"] == "7.50"


def test_cli_errors_are_json_on_stderr(tmp_path: Path, capsys) -> None:
    exit_code = run_cli("show", "--worker", "Anna", "--data-dir", str(tmp_path / "home"), "--json")
    captured = capsys.readouterr()
    assert exit_code == 1
    error = json.loads(captured.err)
    assert error["code"] == "invalid_worker_id"
    assert error["message"]
    assert captured.out == ""


def test_cli_export_refuses_to_overwrite(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    bundle_path = tmp_path / "workers.json"
    bundle_path.write_text("{}", encoding="utf-8")
    assert run_cli("export-data", "--output", str(bundle_path), "--data-dir", str(home), "--json") == 1
    assert json.loads(capsys.readouterr().err)["code"] == "output_exists"


def test_cli_export_refuses_git_worktree_destination(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    exit_code = run_cli(
        "export-data", "--output", str(repo / "workers.json"), "--data-dir", str(tmp_path / "home"), "--json"
    )
    assert exit_code == 1
    assert json.loads(capsys.readouterr().err)["code"] == "export_into_git_repo"
    assert not (repo / "workers.json").exists()


def test_cli_missing_required_argument_is_structured(capsys) -> None:
    exit_code = run_cli("register", "--json")
    captured = capsys.readouterr()
    assert exit_code == 1
    error = json.loads(captured.err)
    assert error["code"] == "invalid_arguments"
    assert captured.out == ""


def test_cli_unknown_subcommand_is_structured(capsys) -> None:
    assert run_cli("frobnicate") == 1
    assert json.loads(capsys.readouterr().err)["code"] == "invalid_arguments"


def test_cli_import_missing_file_is_structured(tmp_path: Path, capsys) -> None:
    exit_code = run_cli(
        "import-data", "--input", str(tmp_path / "nope.json"), "--data-dir", str(tmp_path / "home"), "--json"
    )
    assert exit_code == 1
    assert json.loads(capsys.readouterr().err)["code"] == "input_missing"


def test_cli_rejects_malformed_override_argument(tmp_path: Path, capsys) -> None:
    exit_code = run_cli(
        "register",
        "--worker", "anna",
        "--name", "Anna",
        "--weekdays", "mon",
        "--rate", "7.50",
        "--off", "2026-08-05",
        "--data-dir", str(tmp_path / "home"),
        "--json",
    )
    assert exit_code == 1
    assert json.loads(capsys.readouterr().err)["code"] == "invalid_overrides"


def test_a_currency_label_longer_than_the_limit_is_refused(tmp_path) -> None:
    """An unbounded label would push the one-page A4 sheet onto a second page."""
    from lib.registry import MAX_CURRENCY_LENGTH

    data_dir = resolve_data_dir(str(tmp_path / "data"))
    reg.register_worker(
        data_dir,
        worker_id="anna",
        display_name="Anna Muster",
        weekdays="mon",
        rate="7.50",
        currency="C" * MAX_CURRENCY_LENGTH,
    )  # the limit itself is fine

    with pytest.raises(TimesheetError) as error:
        reg.register_worker(
            data_dir,
            worker_id="bea",
            display_name="Bea Muster",
            weekdays="mon",
            rate="7.50",
            currency="C" * (MAX_CURRENCY_LENGTH + 1),
        )
    assert error.value.code == "invalid_currency"
    assert str(MAX_CURRENCY_LENGTH) in error.value.message
