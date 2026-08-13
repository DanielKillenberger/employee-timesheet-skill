# Reference layout — monthly timesheet

Privacy-safe structural description of the German reference form the built-in
monthly sheet is modelled on. The original photo is **not** committed: it is a
real form and may carry personal data. Everything the renderers need is written
down here instead.

## Structure of the reference form

Portrait A4, one page per month, black on white, no logo:

1. **Title** — a single heading line at the top left ("Stundenrapport").
2. **Identity block** — two labelled lines: the worker's name and the month in
   German long form (`März 2027`). The hourly rate does **not** appear; the form
   is about hours, and pay is a separate conversation (spec R2).
3. **Table header** — three columns: date, hours, remark.
4. **One row per calendar day** — *every* day of the month, including weekends
   and days off, so the sheet reads like a calendar and a missing line is
   visible at a glance. The date cell carries the German weekday abbreviation
   and the dotted date (`Mo, 01.03.2027`).
5. **Grey rows** — non-working days are greyed across the full row width, which
   is what tells the worker "nothing expected here" without any wording.
6. **Blank hour cells** — working days leave the hours cell empty; the worker
   writes into it by hand (on paper) or types into it (in the XLSX).
7. **Total row** — the last row of the table, labelled and holding the sum of
   the hours column. In the XLSX this is a live `SUM` formula, so an edited
   sheet keeps adding up.

## What our renderer does with it

| Reference element      | Built-in sheet                                              |
| ---------------------- | ----------------------------------------------------------- |
| Title                  | `A1`, bold, merged across the three columns                  |
| Name / month           | Labelled rows below the title; name is a literal text cell   |
| Hourly rate            | Omitted unless `--include-rate` is passed                    |
| Table header           | Bold, light grey fill, thin borders                          |
| Day rows               | One per calendar date, from the shared month layout model    |
| Grey rows              | Solid `D9D9D9` across all three columns of every off day     |
| Hours cell             | Empty cell, centred                                          |
| Total                  | `Total Stunden` + `=SUM(<first>:<last>)`                     |
| One page               | `fitToPage` + portrait A4 `page_setup` + explicit print area |

Deliberate differences from the paper form: no signature line and no company
header (the skill produces neutral documents users can print on their own
letterhead), and a remark column, which the paper form has as an unruled
right-hand margin.

## Eyeball checklist

Run before shipping a change to either renderer. Generate a representative
month (a 31-day month with weekend rows and at least one override in each
direction), open the file, and check:

- [ ] **All dates present.** First and last day of the month are both there,
      exactly one row per date, in ascending order, nothing repeated.
- [ ] **Correct greys.** Every greyed row is a non-working day and every
      non-working day is greyed — including override days off, and *excluding*
      exceptional working days that fall on a weekend.
- [ ] **Full-width greys.** The grey covers the whole row, not just one column.
- [ ] **Blank hour cells.** No stray zeros or placeholder text on working days.
- [ ] **Working total.** Typing hours into a few cells changes the total row.
- [ ] **No clipped columns.** Date labels and the header lines are fully
      visible — no `####`, no text cut off at a column edge.
- [ ] **One page.** Print preview shows a single portrait A4 page, no second
      page carrying two stray rows, no shrink so aggressive the text is
      unreadable.
- [ ] **Literal names.** A name or currency label starting with `=`, `+`, `-`
      or `@` shows as text; the spreadsheet does not try to evaluate it.
- [ ] **German throughout.** Weekday abbreviations, month name, and all labels.

## Eyeball checklist — final tally

Run before shipping a change to the tally renderer or the template filler.
Confirm a representative month, generate the tally, and check the built-in PDF
and the filled template XLSX:

- [ ] **Header block.** Worker name, month in German long form, generation date.
- [ ] **All dates present.** Every calendar date once, ascending; days with no
      hours show `0`, not a blank.
- [ ] **Greys agree with the sheet.** The same rows are grey here as on the
      monthly sheet for that worker and month, overrides included.
- [ ] **Totals agree.** The table's total row, the `Total Stunden` summary line
      and the calculation line all state the same number.
- [ ] **Transparent arithmetic.** `hours × rate = gross`, and when rounding
      changed the number the unrounded amount is shown next to it.
- [ ] **No rounding in the presentation.** A four-decimal rate prints with all
      four decimals in both documents.
- [ ] **Disclaimer present.** Gross pay is stated as hours × rate with no
      deductions implied.
- [ ] **One page.** No stray second page carrying the summary block alone.
- [ ] **Template rows intact.** In the filled XLSX the cloned day rows keep the
      marker row's borders, and whatever sits below the marker (total line,
      merged footer) has moved down with its formatting.
- [ ] **German throughout.**

## QA record

| Date       | Build   | Sample                                                             | Viewed with                                                | Result |
| ---------- | ------- | ------------------------------------------------------------------ | ---------------------------------------------------------- | ------ |
| 2026-08-13 | task .2 | `anna` / `2027-03` (31 days, `off 2027-03-02`, `extra 2027-03-06`) | `tools/render_xlsx_preview.py` → A4 PDF → PNG, viewed as an image | pass   |
| 2026-08-13 | task .4 | sheet PDF, `anna` / `2027-03` (31 days, both overrides)            | generated PDF → PNG, viewed as an image                            | pass   |
| 2026-08-13 | task .4 | tally PDF + filled template XLSX, same worker/month, rate `7.3333` | PDF → PNG; XLSX via `tools/render_xlsx_preview.py` → PNG           | pass   |

Reproduce with:

```bash
uv run scripts/timesheet.py generate --worker anna --month 2027-03
uv run tools/render_xlsx_preview.py <data-dir>/output/anna-2027-03.xlsx /tmp/preview.pdf
```

Seen on the rendered page: one portrait A4 page, the whole table in the upper
two thirds, nothing clipped or spilling into a second page; the title, the two
identity lines and the three column headers all fully legible; 31 day rows from
`Mo, 01.03.2027` to `Mi, 31.03.2027`; grey rows on `Di, 02.03.` (override day
off) and every weekend **except** `Sa, 06.03.` (override working day); empty
hour and remark cells throughout; `Total Stunden` in the final row.

The preview draws the stored cell content, so the total row shows the formula
text `=SUM(B6:B36)` where a spreadsheet would show the computed number — that
is the preview tool, not the sheet.

What was additionally checked on the file read back with openpyxl:

- 31 day rows, `Mo, 01.03.2027` through `Mi, 31.03.2027`, each date once, in order.
- Grey rows: `02.03.` (override day off, a Tuesday) plus the seven remaining
  weekend days; `Sa, 06.03.` correctly **not** grey (override working day).
- Hour cells empty on every day; total row `Total Stunden` / `=SUM(B6:B36)`
  spanning exactly the 31 day rows.
- German labels throughout, longest date label 14 characters against a
  18-character date column — no clipping.
- Page geometry: the table occupies ≈4.8 × 7.7 in, inside the ≈7.3 × 10.7 in
  printable area of portrait A4 at 0.5 in margins, with no manual page breaks.
  It therefore fits one page at 100 % scale; `fitToPage` is a safety net rather
  than the thing being relied on. **This is the early proof point: one-page A4
  fit is reliable, so the PDF renderer can share the layout model.**

### Task .4 — sheet PDF and final tally (2026-08-13)

Same worker and month as above, plus a `7.3333` hourly rate so the rounding
disclosure had something to disclose. Reproduce with:

```bash
uv run scripts/timesheet.py generate --worker anna --month 2027-03
uv run scripts/timesheet.py tally    --worker anna --month 2027-03
```

**Sheet PDF** (`anna-2027-03.pdf`), seen on the rendered page: one portrait A4
page; title, the two identity lines and the three column headers legible; 31 day
rows from `Mo, 01.03.2027` to `Mi, 31.03.2027`, each once, in order; grey rows on
`Di, 02.03.` (override day off) and every weekend **except** `Sa, 06.03.`
(override working day) — the greys are identical to the XLSX sheet's, which is
the point of the shared layout model; hours and remark cells empty throughout;
`Total Stunden` as the last row. Nothing clipped, no second page.

**Tally PDF** (`anna-2027-03-abrechnung.pdf`): one portrait A4 page; header
block with name, `März 2027` and the generation date; all 31 dates with their
confirmed hours (`7.25` on working days, `0` on off days) and the same grey
rows; total row `166.75`; summary block `Total Stunden 166.75 h`,
`Stundenlohn 7.3333 CHF`, `Bruttolohn 1222.83 CHF`, and the calculation line
`166.75 h × 7.3333 CHF = 1222.83 CHF (exakt 1222.827775 CHF, kaufmännisch auf
0.01 gerundet)` — the unrounded product is on the page, so the employee can redo
the arithmetic. Disclaimer at the foot in small grey type.

**Filled template XLSX** (`anna-2027-03-abrechnung.xlsx`, bundled default
template), rendered with `tools/render_xlsx_preview.py`: 31 cloned day rows, each
carrying the marker row's borders; the `Total Stunden` line and the merged
disclaimer that sit *below* the marker moved down intact; `Stundenlohn 7.3333`
shown with all four decimals (the two-decimal cell format is applied only to the
gross pay, which is quantized to 0.01 by construction, so no digit can be hidden);
fits one portrait A4 page at 100 %.

Re-checked after the review round that replaced the PDF base font: with the
worker registered as `Anna Šimić`, both documents print the name correctly
(`Š` and `ć` are outside WinAnsi and were black boxes with the standard-14
Helvetica face). Layout, greys, totals and pagination are unchanged by the font
swap.

No LibreOffice was installed in the build environment, so the optional templated
PDF was not produced — the run reported that in plain language and the mandatory
built-in PDF was unaffected, which is exactly the contract in R6.

**Limitation, stated plainly:** no spreadsheet application (Excel, LibreOffice)
was installed in the build environment, so the page above was rendered by
`tools/render_xlsx_preview.py` — a faithful redraw of the parsed workbook at its
own column widths and row heights, not Excel's print engine. It proves the
content and the A4 geometry; it cannot prove how a particular Excel version
paginates. One real print preview should still be run before release, and the
AC11 fresh-install walkthrough is the natural place for it.
