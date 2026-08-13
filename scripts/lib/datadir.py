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
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .errors import TimesheetError

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

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

    @property
    def lock_path(self) -> Path:
        return self.child(".registry.lock")

    @property
    def session_lock_path(self) -> Path:
        return self.child(".extractions.lock")

    @property
    def output_dir(self) -> Path:
        """Folder for generated documents; created owner-only on first use."""
        return self._private_subdir("output")

    @property
    def extractions_dir(self) -> Path:
        """Folder for extraction/confirmation session files."""
        return self._private_subdir("extractions")

    @property
    def evidence_dir(self) -> Path:
        """Folder for the filled-in timesheet photos kept as evidence."""
        return self._private_subdir("filled-timesheets")

    def _private_subdir(self, name: str) -> Path:
        path = self.child(name)
        ensure_private_dir(path)
        return path


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
        ensure_private_dir(path)

    return DataDir(path=path, source=source, warnings=warnings)


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` (and missing parents) owner-only.

    Only directories this function actually creates get their permissions set —
    an existing directory is never chmod-ed, so nothing outside our own data
    folder has its access narrowed.
    """
    if path.exists():
        return
    missing: list[Path] = []
    probe = path
    while not probe.exists() and probe != probe.parent:
        missing.append(probe)
        probe = probe.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=DIR_MODE)
            os.chmod(directory, DIR_MODE)
        except FileExistsError:  # created concurrently — leave it alone
            continue
        except NotImplementedError:  # pragma: no cover - platforms without chmod
            pass
        except OSError as exc:
            raise TimesheetError(
                "data_dir_unwritable",
                f"The folder '{directory}' could not be created: {exc.strerror or exc}.",
                {"path": str(directory)},
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


@contextmanager
def file_lock(path: Path, *, blocking: bool = True) -> Iterator[None]:
    """Hold an exclusive cross-process lock for a read-modify-write cycle.

    Two ``register`` runs at the same time would otherwise both read the old
    registry and the second write would drop the first worker. On platforms
    without ``fcntl``/``msvcrt`` the lock degrades to a no-op (single-user
    desktop use stays correct; see README).
    """
    ensure_private_dir(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, FILE_MODE)
    acquired = False
    try:
        if fcntl is not None:
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(fd, flags)
                acquired = True
            except OSError as exc:
                raise TimesheetError(
                    "data_dir_busy",
                    "Another timesheet command is using this data folder right now. "
                    "Please wait a moment and try again.",
                    {"lock_file": str(path)},
                ) from exc
        elif msvcrt is not None:  # pragma: no cover - Windows only
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(fd, mode, 1)
                acquired = True
            except OSError as exc:
                raise TimesheetError(
                    "data_dir_busy",
                    "Another timesheet command is using this data folder right now. "
                    "Please wait a moment and try again.",
                    {"lock_file": str(path)},
                ) from exc
        yield
    finally:
        if acquired:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows only
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:  # pragma: no cover - best effort
                pass
        os.close(fd)


def reserve_new_file(path: Path) -> None:
    """Claim ``path`` exclusively, failing if it already exists.

    Doing the existence check and the claim in one atomic step closes the gap
    where a file appears between ``exists()`` and the final rename.
    """
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, FILE_MODE)
    except FileExistsError as exc:
        raise TimesheetError(
            "output_exists",
            f"The file '{path}' already exists. Nothing was written. Repeat with --force to replace it.",
            {"path": str(path)},
        ) from exc
    except OSError as exc:
        raise TimesheetError(
            "output_unwritable",
            f"The file '{path}' could not be written: {exc.strerror or exc}.",
            {"path": str(path)},
        ) from exc
    os.close(handle)


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write JSON via tmp file + rename, owner-only where supported.

    The parent directory must already exist — this helper never creates or
    re-permissions directories it does not own.
    """
    if not path.parent.is_dir():
        raise TimesheetError(
            "output_dir_missing",
            f"The folder '{path.parent}' does not exist, so '{path.name}' could not be written.",
            {"path": str(path)},
        )
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


@contextmanager
def atomic_output_file(path: Path, *, suffix: str = "") -> Iterator[Path]:
    """Yield a temp path next to ``path``; replace ``path`` with it on success.

    Generated documents get the same treatment as the registry: a writer that
    truncates its destination first (openpyxl's ``save()`` does) can destroy an
    already-filled-in sheet if the process dies mid-write. Writing beside the
    target and renaming makes the replacement all-or-nothing, and the temp file
    is created owner-only so the finished document never depends on the umask.
    """
    if not path.parent.is_dir():
        raise TimesheetError(
            "output_dir_missing",
            f"The folder '{path.parent}' does not exist, so '{path.name}' could not be written.",
            {"path": str(path)},
        )
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=suffix)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        try:
            os.chmod(tmp_path, FILE_MODE)
        except (NotImplementedError, OSError):  # pragma: no cover
            pass
        yield tmp_path
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


@contextmanager
def atomic_output_files(paths: "list[Path]") -> Iterator[list[Path]]:
    """Yield one temp path per target; publish them all, or publish none.

    A command that writes two documents from one calculation — the monthly
    sheet's XLSX and PDF, the tally's PDF and workbook — must never leave one
    of them refreshed beside a stale copy of the other. Somebody would then
    hand out a January PDF with February's spreadsheet and never notice.

    Every document is rendered to a temp file next to its target first; only
    when they have all been rendered are the targets replaced. A failure at any
    point removes the temp files and leaves every target exactly as it was.

    The final renames are individually atomic but not collectively so — the
    second one can still fail (a target turned into a directory, a permission
    change, a full disk). Each replaced file is therefore kept as a backup
    until the whole set has landed, and a failure part way through puts the
    earlier targets back the way they were.
    """
    staged: list[tuple[Path, Path]] = []
    replaced: list[tuple[Path, Path | None]] = []
    backups: list[Path] = []
    try:
        for path in paths:
            if not path.parent.is_dir():
                raise TimesheetError(
                    "output_dir_missing",
                    f"The folder '{path.parent}' does not exist, so '{path.name}' could not be written.",
                    {"path": str(path)},
                )
            fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                os.chmod(tmp_path, FILE_MODE)
            except (NotImplementedError, OSError):  # pragma: no cover
                pass
            staged.append((path, tmp_path))

        yield [tmp for _, tmp in staged]

        for path, tmp_path in staged:
            backup: Path | None = None
            if path.exists():
                fd, backup_name = tempfile.mkstemp(
                    dir=str(path.parent), prefix=".bak-", suffix=path.suffix
                )
                os.close(fd)
                backup = Path(backup_name)
                backups.append(backup)
                os.replace(path, backup)
            # Restorable from the moment the original moves aside, NOT after
            # the staged file lands: a failure in between would otherwise leave
            # the original sitting in a backup that the cleanup then deletes.
            replaced.append((path, backup))
            os.replace(tmp_path, path)

        for backup in backups:
            backup.unlink(missing_ok=True)
    except BaseException:
        # Undo the publications that already landed, newest first.
        for path, backup in reversed(replaced):
            try:
                if backup is not None:
                    os.replace(backup, path)
                else:
                    path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - nothing better to try
                pass
        for backup in backups:
            # Includes the placeholder of a target whose own backup rename
            # failed, which never made it into `replaced`.
            backup.unlink(missing_ok=True)
        for _, tmp_path in staged:
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
