#!/usr/bin/env python3
"""Package the runtime skill into an uploadable ZIP.

Claude's skill upload expects a ZIP whose *root* holds one folder containing
``SKILL.md`` — so this writes ``employee-timesheet/SKILL.md`` and friends, never
the bare files at the top level.

What goes in is an **allowlist** (``SKILL.md``, ``scripts/``, ``references/``,
``assets/``), not a denylist of things to strip.  A repository that grows a new
folder full of payroll data therefore cannot leak into a release by default: an
unlisted path is simply not packaged.  Inside the allowed trees a second filter
drops caches and any local data file that a developer may have left lying
around (spec R4/AC7).

Usage::

    python3 scripts/package_skill.py --output-dir dist
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Folder name inside the ZIP; also the skill name in ``SKILL.md``.
SKILL_FOLDER = "employee-timesheet"

#: Everything the installed skill needs at runtime, and nothing else.
INCLUDED_FILES = ("SKILL.md",)
INCLUDED_DIRS = ("scripts", "references", "assets")

#: Directory names never packaged, wherever they appear inside an allowed tree.
EXCLUDED_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".flow",
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "extractions",
        "filled-timesheets",
        "output",
        "templates",
        "data",
        "dist",
        "build",
        "tests",
        "tools",
    }
)

#: File names never packaged: local payroll data, and this build tool itself
#: (it builds releases, the installed skill has no use for it).
EXCLUDED_FILE_NAMES = frozenset(
    {"employees.json", ".DS_Store", "package_skill.py"}
)

#: Suffixes never packaged.
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".zip", ".lock"})


class PackagingError(Exception):
    """A problem that stops the package from being written."""


def is_excluded(path: Path) -> bool:
    """True when *path* (a file) must not be packaged."""
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    if path.name.endswith(".timesheet-data.json"):
        return True
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def assert_contained(root: Path, path: Path) -> None:
    """Refuse anything that leaves the repository, symlinks included.

    ``is_file()`` and ``ZipFile.write()`` both follow symlinks, so without this
    a link such as ``assets/logo.png -> ~/.employee-timesheet/employees.json``
    would be packaged under an innocent name and published with the release.
    The name filters cannot see that; only the resolved target can.
    """
    if path.is_symlink():
        raise PackagingError(
            f"'{path.relative_to(root)}' is a symlink. Symlinks are not packaged, "
            "because the file they point at can sit outside the project. "
            "Replace it with a real file."
        )
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise PackagingError(
            f"'{path}' resolves to '{resolved}', outside the project folder "
            f"'{resolved_root}'. Nothing outside the project is packaged."
        )


def collect_files(root: Path) -> list[Path]:
    """Every packageable file, as paths relative to *root*, sorted."""
    selected: list[Path] = []

    for name in INCLUDED_FILES:
        candidate = root / name
        if not candidate.is_file():
            raise PackagingError(
                f"{name} is missing from {root}; the skill cannot be packaged without it."
            )
        assert_contained(root, candidate)
        selected.append(Path(name))

    for dirname in INCLUDED_DIRS:
        directory = root / dirname
        if not directory.is_dir():
            raise PackagingError(
                f"The folder '{dirname}' is missing from {root}; "
                "the skill cannot be packaged without it."
            )
        assert_contained(root, directory)
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(root)
            if is_excluded(relative):
                continue
            # Checked before is_file(), which would follow the link.
            assert_contained(root, path)
            if not path.is_file():
                continue
            selected.append(relative)

    return sorted(set(selected))


def write_zip(root: Path, files: Iterable[Path], destination: Path) -> None:
    """Write *files* into *destination* under the skill folder."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            archive.write(root / relative, f"{SKILL_FOLDER}/{relative.as_posix()}")


def package(root: Path, output_dir: Path, force: bool = True) -> dict:
    """Package the skill and return a JSON-serialisable report."""
    files = collect_files(root)
    destination = output_dir / f"{SKILL_FOLDER}.zip"
    if destination.exists() and not force:
        raise PackagingError(
            f"{destination} already exists. Delete it or pass --force to replace it."
        )
    write_zip(root, files, destination)
    return {
        "command": "package",
        "zip": str(destination),
        "skill_folder": SKILL_FOLDER,
        "file_count": len(files),
        "files": [f"{SKILL_FOLDER}/{path.as_posix()}" for path in files],
        "bytes": destination.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="package_skill",
        description="Build the uploadable employee-timesheet skill ZIP.",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Folder the ZIP is written to (default: dist).",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="Fail instead of replacing an existing ZIP.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        report = package(
            REPO_ROOT, Path(args.output_dir).resolve(), force=not args.no_force
        )
    except PackagingError as error:
        payload = {"code": "packaging_failed", "message": str(error), "detail": {}}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Wrote {report['zip']} ({report['file_count']} files, {report['bytes']} bytes)")
        print(f"Skill folder inside the ZIP: {SKILL_FOLDER}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
