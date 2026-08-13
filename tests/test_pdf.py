"""Monthly sheet PDF: one A4 page for every month length, dates, greys, German text (AC2).

The page-count assertions are the point of this file. The XLSX sheet can lean on
``fitToPage`` and hope the reader honours it; a PDF has already made its mind up
about pagination by the time the file exists, so an overflowing layout is a
silent second page nobody notices until it is printed. pypdf catches it here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

import timesheet
from lib import registry as reg
from lib.datadir import resolve_data_dir
from lib.errors import TimesheetError
from lib.layout import build_month_layout
from lib.pdf_sheet import (
    MARGIN,
    PAGE_SIZE,
    SHEET_COLUMN_WIDTHS,
    escape,
    sheet_pdf_filename,
    write_month_pdf,
)
from lib.xlsx_sheet import LABEL_TOTAL, SHEET_TITLE

SCRIPTS_DIR = Path(timesheet.__file__).resolve().parent


def worker(**overrides):
    record = {
        "id": "anna",
        "display_name": "Anna Muster",
        "working_weekdays": ["mon", "tue", "wed", "thu", "fri"],
        "hourly_rate": "7.50",
        "currency": "CHF",
        "month_overrides": {},
    }
    record.update(overrides)
    return record


def written_pdf(tmp_path: Path, record=None, month="2027-03", **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    layout = build_month_layout(record or worker(), month)
    path = tmp_path / sheet_pdf_filename(layout)
    write_month_pdf(layout, path, **kwargs)
    return path, layout


def page_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


# --------------------------------------------------------------------------
# AC2 — one portrait A4 page, whatever the month length
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("month", "expected_days"),
    [("2027-03", 31), ("2027-04", 30), ("2027-02", 28), ("2028-02", 29)],
)
def test_every_month_length_fits_one_portrait_a4_page(
    tmp_path: Path, month: str, expected_days: int
) -> None:
    path, layout = written_pdf(tmp_path, month=month, include_rate=True, hourly_rate="7.50", currency="CHF")
    reader = PdfReader(str(path))

    assert len(layout.rows) == expected_days
    assert len(reader.pages) == 1

    box = reader.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (
        round(PAGE_SIZE[0]),
        round(PAGE_SIZE[1]),
    )
    assert float(box.height) > float(box.width)  # portrait


def test_the_worst_case_month_leaves_headroom_on_the_page(tmp_path: Path) -> None:
    """31 days plus the rate line must not merely fit — it must fit with slack.

    A layout that is exactly one page today becomes two pages the moment anyone
    adds a line, so the check is on the geometry, not only on the page count.
    """
    from lib.pdf_sheet import TABLE_HEADER_HEIGHT, TABLE_ROW_HEIGHT

    table_height = TABLE_HEADER_HEIGHT + TABLE_ROW_HEIGHT * (31 + 1)  # 31 days + total row
    header_block = 17 + 6 + 12.5 * 3 + 8  # title, spacer, three identity lines, spacer
    available = PAGE_SIZE[1] - 2 * MARGIN

    assert table_height + header_block < available * 0.85
    assert sum(SHEET_COLUMN_WIDTHS) <= PAGE_SIZE[0] - 2 * MARGIN


# --------------------------------------------------------------------------
# content: every date once, German labels, blank hours
# --------------------------------------------------------------------------


def test_every_calendar_date_appears_exactly_once(tmp_path: Path) -> None:
    path, layout = written_pdf(tmp_path)
    text = page_text(path)
    for row in layout.rows:
        assert text.count(row.label) == 1, row.label


def test_the_pdf_carries_the_german_header_block_and_total_row(tmp_path: Path) -> None:
    path, layout = written_pdf(tmp_path)
    text = page_text(path)
    assert SHEET_TITLE in text
    assert layout.title in text  # "März 2027" — umlaut survives the built-in font
    assert layout.display_name in text
    assert LABEL_TOTAL in text


def test_the_rate_is_omitted_unless_it_is_asked_for(tmp_path: Path) -> None:
    without, _ = written_pdf(tmp_path / "a", hourly_rate="7.50", currency="CHF")
    assert "7.50" not in page_text(without)

    with_rate, _ = written_pdf(
        tmp_path / "b", include_rate=True, hourly_rate="7.50", currency="CHF"
    )
    assert "7.50 CHF" in page_text(with_rate)


def test_grey_off_day_rows_match_the_resolved_layout(tmp_path: Path) -> None:
    """The greys are a table style, so assert on the style the renderer builds."""
    from lib.pdf_sheet import GREY_ROW, build_sheet_story

    record = worker(month_overrides={"2027-03": {"off": ["2027-03-02"], "extra": ["2027-03-06"]}})
    layout = build_month_layout(record, "2027-03")
    table = next(item for item in build_sheet_story(layout) if hasattr(item, "_cellStyles"))

    greyed = {
        command[1][1]
        for command in table._bkgrndcmds
        if command[0] == "BACKGROUND" and command[3] == GREY_ROW
    }
    expected = {index for index, row in enumerate(layout.rows, start=1) if not row.working}
    assert greyed == expected
    assert 2 in greyed  # 02.03. — override day off, a Tuesday
    assert 6 not in greyed  # 06.03. — override working day, a Saturday


def test_hour_and_remark_cells_are_left_empty(tmp_path: Path) -> None:
    from lib.pdf_sheet import build_sheet_story

    layout = build_month_layout(worker(), "2027-03")
    table = next(item for item in build_sheet_story(layout) if hasattr(item, "_cellStyles"))
    body = table._cellvalues[1:-1]
    assert len(body) == 31
    assert all(row[1] == "" and row[2] == "" for row in body)


# --------------------------------------------------------------------------
# text safety — a name is text, not markup
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Anna <b>Muster</b>", "Meier & Söhne", "=cmd()"])
def test_markup_in_a_name_is_printed_literally(tmp_path: Path, name: str) -> None:
    path, _ = written_pdf(tmp_path, worker(display_name=name))
    assert name in page_text(path)


def test_escape_neutralises_reportlab_markup() -> None:
    assert escape("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
    assert escape(None) == ""


# --------------------------------------------------------------------------
# the generate subcommand writes both documents
# --------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path: Path):
    directory = resolve_data_dir(str(tmp_path / "data"))
    reg.register_worker(
        directory,
        worker_id="anna",
        display_name="Anna Muster",
        weekdays="mon,tue,wed,thu,fri",
        rate="7.50",
    )
    return directory


def run_cli(*args: str, data_dir) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "timesheet.py"), *args, "--data-dir", str(data_dir.path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    return {"returncode": completed.returncode, "payload": json.loads(stream)}


def test_generate_writes_the_xlsx_and_the_pdf(data_dir) -> None:
    result = run_cli("generate", "--worker", "anna", "--month", "2027-03", data_dir=data_dir)
    assert result["returncode"] == 0

    files = result["payload"]["files"]
    assert Path(files["xlsx"]).is_file()
    assert Path(files["pdf"]).is_file()
    assert len(PdfReader(files["pdf"]).pages) == 1


def test_generate_refuses_to_overwrite_either_document(data_dir) -> None:
    first = run_cli("generate", "--worker", "anna", "--month", "2027-03", data_dir=data_dir)
    pdf = Path(first["payload"]["files"]["pdf"])
    before = pdf.read_bytes()

    second = run_cli("generate", "--worker", "anna", "--month", "2027-03", data_dir=data_dir)
    assert second["returncode"] != 0
    assert second["payload"]["code"] == "output_exists"
    assert pdf.read_bytes() == before

    forced = run_cli("generate", "--worker", "anna", "--month", "2027-03", "--force", data_dir=data_dir)
    assert forced["returncode"] == 0


def failing_generate(data_dir, monkeypatch, *extra_args: str) -> None:
    """Run `generate` with a PDF renderer that always explodes."""
    import timesheet as cli

    def boom(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(cli, "render_month_pdf", boom)
    args = cli.build_parser().parse_args(
        [
            "generate",
            "--worker",
            "anna",
            "--month",
            "2027-03",
            "--data-dir",
            str(data_dir.path),
            *extra_args,
        ]
    )
    with pytest.raises(RuntimeError):
        cli.cmd_generate(args)


def test_a_failed_pdf_leaves_no_empty_claim_behind(data_dir, monkeypatch) -> None:
    """The XLSX claim and the PDF claim are both released when rendering fails."""
    failing_generate(data_dir, monkeypatch)
    assert list(data_dir.output_dir.iterdir()) == []


def test_a_failed_pdf_never_leaves_a_fresh_xlsx_beside_a_stale_pdf(data_dir, monkeypatch) -> None:
    """--force must not publish half of a document set (review finding 5)."""
    first = run_cli("generate", "--worker", "anna", "--month", "2027-03", data_dir=data_dir)
    xlsx = Path(first["payload"]["files"]["xlsx"])
    pdf = Path(first["payload"]["files"]["pdf"])
    before_xlsx, before_pdf = xlsx.read_bytes(), pdf.read_bytes()

    failing_generate(data_dir, monkeypatch, "--force")

    assert xlsx.read_bytes() == before_xlsx, "the XLSX was replaced although the PDF failed"
    assert pdf.read_bytes() == before_pdf
    assert sorted(item.name for item in data_dir.output_dir.iterdir()) == sorted(
        [xlsx.name, pdf.name]
    )


# --------------------------------------------------------------------------
# printable characters — a name is printed correctly or not at all
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Łukasz Nowak", "Ivan Šimić", "Jozef Novák", "Anna Müller"])
def test_central_european_names_are_printed_faithfully(tmp_path: Path, name: str) -> None:
    path, _ = written_pdf(tmp_path, worker(display_name=name))
    text = page_text(path)
    assert name in text
    assert "■" not in text  # never a black box


@pytest.mark.parametrize("name", ["李明", "Мария Иванова"])
def test_a_name_the_font_cannot_draw_is_refused_not_mangled(tmp_path: Path, name: str) -> None:
    """Silently printing boxes over someone's name on a pay document is worse."""
    from lib.pdf_sheet import ensure_printable

    with pytest.raises(TimesheetError) as error:
        written_pdf(tmp_path, worker(display_name=name))
    assert error.value.code == "unprintable_text"
    assert name[0] in error.value.message

    # ...and nothing was left behind by the refusal.
    assert not list(tmp_path.glob("*.pdf"))
    assert ensure_printable("Anna Müller", subject="The name") == "Anna Müller"


def test_a_maximum_length_name_and_currency_still_fit_one_page(tmp_path: Path) -> None:
    """The one-page guarantee has to hold for the longest registrable input."""
    from lib.registry import MAX_CURRENCY_LENGTH, MAX_NAME_LENGTH

    path, _ = written_pdf(
        tmp_path,
        worker(display_name="Ä" * MAX_NAME_LENGTH),
        month="2027-03",
        include_rate=True,
        hourly_rate="99999.9999",
        currency="C" * MAX_CURRENCY_LENGTH,
    )
    assert len(PdfReader(str(path)).pages) == 1


# --------------------------------------------------------------------------
# atomic_output_files — all or nothing, including during publication
# --------------------------------------------------------------------------


def test_a_failed_second_rename_puts_the_first_target_back(tmp_path: Path) -> None:
    """Publishing is a sequence of renames; a failure half way must not split the set."""
    from lib.datadir import atomic_output_files

    first = tmp_path / "one.pdf"
    first.write_bytes(b"old one")
    second = tmp_path / "two.xlsx"
    second.mkdir()  # a directory here makes the second rename fail

    with pytest.raises(OSError):
        with atomic_output_files([first, second]) as (staged_first, staged_second):
            staged_first.write_bytes(b"new one")
            staged_second.write_bytes(b"new two")

    assert first.read_bytes() == b"old one", "the first document was published on its own"
    assert second.is_dir()
    leftovers = [item.name for item in tmp_path.iterdir() if item.name.startswith(".")]
    assert leftovers == [], f"temporary files left behind: {leftovers}"


def test_a_failed_second_rename_removes_a_first_target_that_was_new(tmp_path: Path) -> None:
    from lib.datadir import atomic_output_files

    first = tmp_path / "one.pdf"  # does not exist yet
    second = tmp_path / "two.xlsx"
    second.mkdir()

    with pytest.raises(OSError):
        with atomic_output_files([first, second]) as (staged_first, staged_second):
            staged_first.write_bytes(b"new one")
            staged_second.write_bytes(b"new two")

    assert not first.exists(), "a half-published set left a new file behind"


def test_publishing_a_full_set_leaves_no_backups(tmp_path: Path) -> None:
    from lib.datadir import atomic_output_files

    first, second = tmp_path / "one.pdf", tmp_path / "two.xlsx"
    first.write_bytes(b"old one")

    with atomic_output_files([first, second]) as (staged_first, staged_second):
        staged_first.write_bytes(b"new one")
        staged_second.write_bytes(b"new two")

    assert first.read_bytes() == b"new one"
    assert second.read_bytes() == b"new two"
    assert [item.name for item in tmp_path.iterdir() if item.name.startswith(".")] == []


def test_a_failed_publish_after_the_backup_move_restores_the_original(
    tmp_path: Path, monkeypatch
) -> None:
    """Fault injection between "original moved aside" and "replacement lands".

    That window is where a two-step publish can destroy a document outright:
    the original is no longer at its own path, and the new one never arrived.
    """
    from lib import datadir

    first, second = tmp_path / "one.pdf", tmp_path / "two.xlsx"
    first.write_bytes(b"old one")
    second.write_bytes(b"old two")

    real_replace = os.replace

    def flaky_replace(src, dst):
        # Fail only the second document's staged -> target rename, after its
        # original has already been moved to a backup.
        if Path(dst) == second and Path(src).name.startswith(".tmp-"):
            raise OSError("injected failure while publishing")
        return real_replace(src, dst)

    monkeypatch.setattr(datadir.os, "replace", flaky_replace)

    with pytest.raises(OSError):
        with datadir.atomic_output_files([first, second]) as (staged_first, staged_second):
            staged_first.write_bytes(b"new one")
            staged_second.write_bytes(b"new two")

    assert first.read_bytes() == b"old one"
    assert second.read_bytes() == b"old two", "the original was destroyed, not restored"
    assert [item.name for item in tmp_path.iterdir() if item.name.startswith(".")] == []
