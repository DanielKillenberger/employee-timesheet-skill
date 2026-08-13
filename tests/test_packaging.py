"""Packaging tests — the ZIP is the release artifact, so it is checked hard.

Two failure modes matter and both are silent:

* a layout Claude's upload rejects (files at the ZIP root instead of one folder
  containing ``SKILL.md``), and
* a leak — an ``employees.json``, a filled-in sheet photo or a generated
  ``abrechnung.pdf`` riding along into a public release (spec AC7).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from package_skill import (
    SKILL_FOLDER,
    PackagingError,
    collect_files,
    is_excluded,
    package,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILL_MD_MAX_NAME = 64
SKILL_MD_MAX_DESCRIPTION = 1024


@pytest.fixture(scope="module")
def built_zip(tmp_path_factory) -> Path:
    report = package(REPO_ROOT, tmp_path_factory.mktemp("dist"))
    return Path(report["zip"])


@pytest.fixture(scope="module")
def names(built_zip: Path) -> list[str]:
    with zipfile.ZipFile(built_zip) as archive:
        return archive.namelist()


def test_zip_is_named_after_the_skill(built_zip: Path) -> None:
    assert built_zip.name == "employee-timesheet.zip"
    assert built_zip.stat().st_size > 0


def test_single_folder_at_zip_root(names: list[str]) -> None:
    roots = {name.split("/", 1)[0] for name in names}
    assert roots == {SKILL_FOLDER}


def test_skill_md_sits_directly_in_that_folder(names: list[str]) -> None:
    assert f"{SKILL_FOLDER}/SKILL.md" in names


def test_required_resources_are_present(names: list[str]) -> None:
    for required in (
        "SKILL.md",
        "scripts/timesheet.py",
        "scripts/lib/registry.py",
        "scripts/lib/extraction.py",
        "scripts/lib/tally.py",
        "scripts/lib/pdf_sheet.py",
        "scripts/lib/xlsx_sheet.py",
        "references/extraction-schema.md",
        "references/templates.md",
        "references/reference-layout.md",
    ):
        assert f"{SKILL_FOLDER}/{required}" in names, required


def test_default_tally_template_ships(built_zip: Path, names: list[str]) -> None:
    """Without it an installed skill has no template to fall back on (R6)."""
    entry = f"{SKILL_FOLDER}/assets/default-tally-template.xlsx"
    assert entry in names
    with zipfile.ZipFile(built_zip) as archive:
        payload = archive.read(entry)
    assert payload[:2] == b"PK", "the bundled template must be a real xlsx"
    with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()


def test_unpacks_into_a_usable_skill_folder(built_zip: Path, tmp_path: Path) -> None:
    with zipfile.ZipFile(built_zip) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / SKILL_FOLDER
    assert folder.is_dir()
    assert (folder / "SKILL.md").is_file()
    assert (folder / "scripts" / "timesheet.py").is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == [SKILL_FOLDER]


# --- exclusions -----------------------------------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        ".git",
        ".flow",
        "tests",
        "tools",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "output",
        "extractions",
        "filled-timesheets",
        "templates",
        "data",
    ],
)
def test_no_forbidden_directory_anywhere(names: list[str], forbidden: str) -> None:
    for name in names:
        assert forbidden not in name.split("/"), f"{forbidden} leaked via {name}"


def test_no_registry_or_local_data_files(names: list[str]) -> None:
    for name in names:
        base = name.rsplit("/", 1)[-1]
        assert base != "employees.json"
        assert not base.endswith(".timesheet-data.json")
        assert not base.endswith(".pyc")
        assert not base.endswith(".zip")


def test_no_generated_documents_or_photos(names: list[str]) -> None:
    """A worker sheet, tally or scan must never ride along in a release."""
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        assert not base.endswith(".pdf"), name
        assert not base.endswith((".jpg", ".jpeg", ".png", ".heic")), name
        if base.endswith(".xlsx"):
            assert name == f"{SKILL_FOLDER}/assets/default-tally-template.xlsx", name


def test_is_excluded_catches_stray_local_data() -> None:
    assert is_excluded(Path("assets/employees.json"))
    assert is_excluded(Path("scripts/__pycache__/timesheet.cpython-311.pyc"))
    assert is_excluded(Path("references/output/anna-2026-03.pdf"))
    assert is_excluded(Path("assets/filled-timesheets/scan.jpg"))
    assert is_excluded(Path("assets/anna.timesheet-data.json"))
    assert not is_excluded(Path("assets/default-tally-template.xlsx"))
    assert not is_excluded(Path("scripts/timesheet.py"))


def test_collect_files_refuses_an_incomplete_repository(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n")
    with pytest.raises(PackagingError) as excinfo:
        collect_files(tmp_path)
    assert "scripts" in str(excinfo.value)


def test_collect_files_refuses_a_missing_skill_md(tmp_path: Path) -> None:
    for name in ("scripts", "references", "assets"):
        (tmp_path / name).mkdir()
    with pytest.raises(PackagingError) as excinfo:
        collect_files(tmp_path)
    assert "SKILL.md" in str(excinfo.value)


def test_no_force_refuses_to_replace(tmp_path: Path) -> None:
    package(REPO_ROOT, tmp_path)
    with pytest.raises(PackagingError):
        package(REPO_ROOT, tmp_path, force=False)


# --- SKILL.md frontmatter -------------------------------------------------


@pytest.fixture(scope="module")
def frontmatter(built_zip: Path) -> dict[str, str]:
    """Parsed from the *packaged* SKILL.md, which is what Claude will read."""
    with zipfile.ZipFile(built_zip) as archive:
        text = archive.read(f"{SKILL_FOLDER}/SKILL.md").decode("utf-8")
    assert text.startswith("---\n")
    block, _, body = text[4:].partition("\n---\n")
    assert body.strip(), "SKILL.md needs a body"
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if line.startswith(("name:", "description:")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_skill_name_is_valid(frontmatter: dict[str, str]) -> None:
    name = frontmatter["name"]
    assert len(name) <= SKILL_MD_MAX_NAME
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), name
    assert "claude" not in name and "anthropic" not in name
    assert name == SKILL_FOLDER, "folder in the ZIP must match the skill name"


def test_skill_description_is_within_limits(frontmatter: dict[str, str]) -> None:
    description = frontmatter["description"]
    assert 0 < len(description) <= SKILL_MD_MAX_DESCRIPTION
    lowered = description.lower()
    assert "timesheet" in lowered, "description must say what the skill is for"
    assert "use when" in lowered, "description must say when to use the skill"


def test_skill_body_stays_small(built_zip: Path) -> None:
    """Body must stay comfortably under the 5k-token budget."""
    with zipfile.ZipFile(built_zip) as archive:
        text = archive.read(f"{SKILL_FOLDER}/SKILL.md").decode("utf-8")
    body = text[4:].partition("\n---\n")[2]
    assert len(body) < 18_000, "SKILL.md body is growing past its token budget"


def test_skill_body_points_only_one_level_deep(built_zip: Path, names: list[str]) -> None:
    """Every referenced resource file must actually be in the package."""
    with zipfile.ZipFile(built_zip) as archive:
        body = archive.read(f"{SKILL_FOLDER}/SKILL.md").decode("utf-8")
    referenced = set(re.findall(r"`((?:references|assets|scripts)/[\w./-]+)`", body))
    assert referenced, "SKILL.md should point at its resources"
    for path in referenced:
        assert f"{SKILL_FOLDER}/{path}" in names, path
