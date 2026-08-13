"""Local data directory resolution, path safety and atomic writes.

Payroll data never belongs in git and never belongs in a throwaway sandbox
folder, so resolution is deliberately opinionated (plan decision 7):

precedence   ``--data-dir`` > ``TIMESHEET_DATA_DIR`` > ``~/.employee-timesheet``
refusal      a data dir inside a git worktree is refused in plain language
             (``--allow-repo-data`` exists for tests only)
warning      a data dir inside an ephemeral path (``/tmp`` and friends) still
             works but reports a JSON warning, because it will be lost
permissions  directories 0700, files 0600 where the platform supports it
writes       tmp file + ``os.replace`` so a crash never truncates the registry
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import TimesheetError

ENV_VAR = "TIMESHEET_DATA_DIR"
DEFAULT_DATA_DIR = Path("~/.employee-timesheet")

DIR_MODE = 0o700
FILE_MODE = 0o600


@dataclass
class DataDir:
    """A resolved, safe-to-write data directory."""

    path: Path
    source: str
    warnings: list[str] = field(default_factory=list)

    def child(self, *parts: str) -> Path:
        """Resolve a path beneath the data dir, refusing any escape."""
        return safe_child(self.path, *parts)

    @property
    def registry_path(self) -> Path:
        return self.child("employees.json")


def _ephemeral_roots() -> list[Path]:
    roots = {"/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp", tempfile.gettempdir()}
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(Path(root).expanduser().resolve())
        except OSError:  # pragma: no cover - unusual platforms
            continue
    return resolved


def _is_ephemeral(path: Path) -> bool:
    for root in _ephemeral_roots():
        if path == root or root in path.parents:
            return True
    return False


def find_git_worktree(path: Path) -> Path | None:
    """Return the git worktree root containing ``path``, or None."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_data_dir(
    cli_value: str | None = None,
    *,
    env: dict[str, str] | None = None,
    allow_repo_data: bool = False,
    create: bool = True,
) -> DataDir:
    environ = os.environ if env is None else env

    if cli_value:
        raw, source = cli_value, "--data-dir"
    elif environ.get(ENV_VAR):
        raw, source = environ[ENV_VAR], ENV_VAR
    else:
        raw, source = str(DEFAULT_DATA_DIR), "default"

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()

    warnings: list[str] = []

    worktree = find_git_worktree(path)
    if worktree is not None and not allow_repo_data:
        raise TimesheetError(
            "data_dir_in_git_repo",
            "The data folder "
            f"'{path}' sits inside the code folder '{worktree}', which is managed by git. "
            "Employee and pay data must never land somewhere it could be committed. "
            "Please choose a folder outside this project, for example your home folder.",
            {"data_dir": str(path), "git_worktree": str(worktree), "source": source},
        )

    if _is_ephemeral(path):
        warnings.append(
            f"The data folder '{path}' is in a temporary location and may be deleted when "
            "this session ends. Use 'export-data' to keep a copy of the worker registry."
        )

    if create:
        _mkdir_owner_only(path)

    return DataDir(path=path, source=source, warnings=warnings)


def _mkdir_owner_only(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, DIR_MODE)
    except NotImplementedError:  # pragma: no cover - platforms without chmod
        pass
    except OSError as exc:
        raise TimesheetError(
            "data_dir_unwritable",
            f"The data folder '{path}' could not be created: {exc.strerror or exc}.",
            {"data_dir": str(path)},
        ) from exc


def safe_child(base: Path, *parts: str) -> Path:
    """Resolve ``base/parts`` and assert the result stays beneath ``base``."""
    base_resolved = base.resolve()
    candidate = base_resolved
    for part in parts:
        if part in ("", ".", "..") or "/" in part or "\\" in part or os.path.isabs(part):
            raise TimesheetError(
                "unsafe_path",
                f"'{part}' is not a valid file or folder name.",
                {"base": str(base_resolved), "part": part},
            )
        candidate = candidate / part
    candidate = candidate.resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise TimesheetError(
            "unsafe_path",
            "That location is outside the data folder and was refused.",
            {"base": str(base_resolved), "resolved": str(candidate)},
        )
    return candidate


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write JSON via tmp file + rename, owner-only where supported."""
    _mkdir_owner_only(path.parent)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_path, FILE_MODE)
        except (NotImplementedError, OSError):  # pragma: no cover
            pass
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise TimesheetError(
            "corrupt_json",
            f"The file '{path}' is not readable as JSON ({exc.msg}, line {exc.lineno}).",
            {"path": str(path)},
        ) from exc
