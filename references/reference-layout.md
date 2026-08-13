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
