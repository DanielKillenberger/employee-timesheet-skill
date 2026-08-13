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

## QA record

| Date       | Build  | Sample                                                      | Result |
| ---------- | ------ | ----------------------------------------------------------- | ------ |
| 2026-08-13 | task .2 | `anna` / `2027-03` (31 days, `off 2027-03-02`, `extra 2027-03-06`) | pass, with the limitation noted below |

What was inspected, on the file actually written to disk and read back:

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

**Limitation, stated plainly:** no spreadsheet application (Excel, LibreOffice)
was available in the build environment, so this pass inspected the parsed
workbook and computed print geometry rather than an on-screen print preview.
The visual print-preview check is carried by the PDF sheet in task `.4` and by
the fresh-install walkthrough (AC11), where a rendered document exists to look
at. Anyone with Excel to hand should still run the checklist above once.
