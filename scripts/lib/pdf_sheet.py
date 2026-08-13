"""Render a month layout as a print-ready one-page portrait A4 PDF (spec R2).

The PDF is the paper twin of the XLSX sheet: same title, same identity block,
same three columns, same grey off-day rows, same total row. Both renderers
consume :mod:`lib.layout`, so the two documents can never disagree about which
dates exist or which of them are days off — there is no XLSX-to-PDF conversion
anywhere in this skill, and therefore no dependency on an external converter.

Two things are load-bearing:

* **One portrait A4 page for every month length.** Row heights and font sizes
  are fixed rather than elastic, and the worst case (31 days + header + total,
  with the optional rate line) is dimensioned to leave headroom inside the
  printable area. ``tests/test_pdf.py`` asserts the page count with pypdf for
  every month length, so a future layout change that overflows fails loudly.
* **German text with the built-in fonts.** Helvetica is written with
  WinAnsiEncoding, which covers the umlauts and ``ß`` the German labels need,
  so no font file has to be embedded or shipped.

This module also holds the small PDF primitives (page frame, fonts, colours,
text escaping) that :mod:`lib.tally` reuses, so the sheet and the final tally
look like they came from the same office.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .datadir import atomic_output_file
from .layout import MonthLayout
from .xlsx_sheet import (
    COLUMN_HEADERS,
    LABEL_MONTH,
    LABEL_RATE,
    LABEL_TOTAL,
    LABEL_WORKER,
    SHEET_TITLE,
)

BASE_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"

PAGE_SIZE = A4
MARGIN = 18 * mm

#: Fixed geometry — the reason one A4 page is a guarantee and not a hope.
TABLE_FONT_SIZE = 8.5
TABLE_ROW_HEIGHT = 15.5
TABLE_HEADER_HEIGHT = 17

GREY_ROW = colors.HexColor("#D9D9D9")
HEADER_FILL = colors.HexColor("#EFEFEF")
GRID_COLOUR = colors.HexColor("#999999")

SHEET_COLUMN_WIDTHS = (46 * mm, 26 * mm, 102 * mm)

TITLE_STYLE = ParagraphStyle(
    "TimesheetTitle",
    fontName=BOLD_FONT,
    fontSize=14,
    leading=17,
    alignment=TA_LEFT,
    spaceAfter=0,
)
LINE_STYLE = ParagraphStyle(
    "TimesheetLine",
    fontName=BASE_FONT,
    fontSize=9.5,
    leading=12.5,
    alignment=TA_LEFT,
)
NOTE_STYLE = ParagraphStyle(
    "TimesheetNote",
    fontName=BASE_FONT,
    fontSize=7.5,
    leading=10,
    textColor=colors.HexColor("#555555"),
    alignment=TA_LEFT,
)


def escape(value: object) -> str:
    """Escape text for reportlab's mini-HTML paragraph markup.

    A worker called ``Anna & Co <AG>`` must print as written; reportlab would
    otherwise read the angle brackets as markup and either swallow the name or
    raise a parse error deep inside the layout engine.
    """
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def labelled_line(label: str, value: object) -> Paragraph:
    """One ``Label: value`` line of the identity block, label in bold."""
    return Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", LINE_STYLE)


def build_document(path: Path | str, *, title: str, author: str = "") -> SimpleDocTemplate:
    """A portrait A4 document with our margins and honest PDF metadata."""
    return SimpleDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=title,
        author=author,
        subject=title,
        creator="employee-timesheet skill",
    )


def table_style(*, grey_rows: Sequence[int] = (), total_row: int | None = None) -> TableStyle:
    """Shared table look: bordered grid, grey header, grey off-day rows.

    ``grey_rows`` and ``total_row`` are absolute table row indices (0 = header).
    """
    commands: list[tuple[Any, ...]] = [
        ("FONTNAME", (0, 0), (-1, -1), BASE_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), TABLE_FONT_SIZE),
        ("FONTNAME", (0, 0), (-1, 0), BOLD_FONT),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID_COLOUR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    for index in grey_rows:
        commands.append(("BACKGROUND", (0, index), (-1, index), GREY_ROW))
    if total_row is not None:
        commands.append(("FONTNAME", (0, total_row), (-1, total_row), BOLD_FONT))
    return TableStyle(commands)


def build_sheet_story(
    layout: MonthLayout,
    *,
    include_rate: bool = False,
    hourly_rate: str | None = None,
    currency: str | None = None,
) -> list[Any]:
    """The flowables of one monthly sheet, in print order."""
    story: list[Any] = [
        Paragraph(escape(SHEET_TITLE), TITLE_STYLE),
        Spacer(1, 6),
        labelled_line(LABEL_WORKER, layout.display_name),
        labelled_line(LABEL_MONTH, layout.title),
    ]
    if include_rate:
        rate_text = " ".join(part for part in (hourly_rate, currency) if part)
        story.append(labelled_line(LABEL_RATE, rate_text))
    story.append(Spacer(1, 8))

    rows: list[list[str]] = [list(COLUMN_HEADERS)]
    grey_rows: list[int] = []
    for index, day in enumerate(layout.rows, start=1):
        # Hours and remark stay empty: this sheet is filled in by hand.
        rows.append([day.label, "", ""])
        if not day.working:
            grey_rows.append(index)
    rows.append([LABEL_TOTAL, "", ""])
    total_row = len(rows) - 1

    heights = [TABLE_HEADER_HEIGHT] + [TABLE_ROW_HEIGHT] * (len(rows) - 1)
    table = Table(rows, colWidths=list(SHEET_COLUMN_WIDTHS), rowHeights=heights, repeatRows=0)
    table.setStyle(table_style(grey_rows=grey_rows, total_row=total_row))
    story.append(table)
    return story


def sheet_pdf_filename(layout: MonthLayout) -> str:
    return f"{layout.worker_id}-{layout.month}.pdf"


def write_month_pdf(
    layout: MonthLayout,
    path: Path,
    *,
    include_rate: bool = False,
    hourly_rate: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Write the monthly sheet PDF to ``path`` and describe what was produced."""
    story = build_sheet_story(
        layout,
        include_rate=include_rate,
        hourly_rate=hourly_rate,
        currency=currency,
    )
    # Same discipline as the XLSX writer: build beside the target and rename, so
    # a crash mid-render never leaves a truncated document where a good one was.
    with atomic_output_file(path, suffix=".pdf") as tmp_path:
        document = build_document(
            tmp_path,
            title=f"{SHEET_TITLE} {layout.title} - {layout.display_name}",
        )
        document.build(story)
    return {
        "path": str(path),
        "rows": len(layout.rows),
        "working_days": len(layout.working_rows),
        "off_days": len(layout.off_rows),
    }
