"""Monthly sheet PDF: one A4 page for every month length, dates, greys, German text (AC2).

The page-count assertions are the point of this file. The XLSX sheet can lean on
``fitToPage`` and hope the reader honours it; a PDF has already made its mind up
about pagination by the time the file exists, so an overflowing layout is a
silent second page nobody notices until it is printed. pypdf catches it here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

import timesheet
from lib import registry as reg
from lib.datadir import resolve_data_dir
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


def test_a_failed_pdf_leaves_no_empty_claim_behind(data_dir, monkeypatch) -> None:
    """The XLSX claim and the PDF claim are both released when rendering fails."""
    import timesheet as cli

    def boom(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(cli, "write_month_pdf", boom)
    parser = cli.build_parser()
    args = parser.parse_args(
        ["generate", "--worker", "anna", "--month", "2027-03", "--data-dir", str(data_dir.path)]
    )
    with pytest.raises(RuntimeError):
        cli.cmd_generate(args)

    assert list(data_dir.output_dir.iterdir()) == []
