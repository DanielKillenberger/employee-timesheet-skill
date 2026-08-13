# Your own template for the final tally

The final tally is the document you hand or send to your employee at the end of
the month. The skill always produces a clean built-in PDF for it — you never
have to do anything for that one.

On top of that, you can supply **your own Excel file** as a template, for
example on your letterhead or in the wording your accountant prefers. This page
explains how, in plain terms.

## The short version

1. Make an Excel file (`.xlsx`) that looks the way you want.
2. Wherever a number or a name should appear, type a **placeholder** — a word in
   double curly braces, e.g. `{{worker_name}}`.
3. Save it as `tally.xlsx` in the `templates` folder of your data folder, or
   point at it with `--template /path/to/your-file.xlsx`.
4. Run the tally as usual. The skill fills your file in and saves a copy — your
   original template is never modified.

## The placeholders

All of these must appear somewhere in the file. If one is missing, the skill
tells you exactly which one and stops — it will never quietly hand you a
document with a blank where the pay should be.

| Placeholder           | Becomes                                              |
| --------------------- | ---------------------------------------------------- |
| `{{worker_name}}`     | The employee's name, e.g. `Anna Muster`               |
| `{{month_title}}`     | The month in German, e.g. `März 2027`                 |
| `{{generation_date}}` | The day the document was made, e.g. `13.08.2026`      |
| `{{total_hours}}`     | The confirmed total hours, e.g. `172.5`               |
| `{{rate}}`            | The registered hourly rate, e.g. `7.50`               |
| `{{currency}}`        | The currency label, e.g. `CHF`                        |
| `{{gross_pay}}`       | Hours × rate, e.g. `1293.75`                          |
| `{{day_rows}}`        | The daily hours — see below                           |

A placeholder can sit in a cell on its own, or inside a sentence:
`Abrechnung für {{worker_name}}, {{month_title}}` works fine.

**Numbers stay numbers.** When a cell contains *nothing but*
`{{total_hours}}`, `{{rate}}` or `{{gross_pay}}`, the skill writes a real
number into it, so your own formulas (`=B9*B11`, a currency format, a chart)
keep working. In a sentence, the same placeholder becomes text.

## The daily hours: `{{day_rows}}`

Put `{{day_rows}}` in **one** cell — the cell where the first date should
appear. That row is your *marker row*:

|     | A               | B         |
| --- | --------------- | --------- |
| 7   | **Datum**       | **Stunden** |
| 8   | `{{day_rows}}`  |           |
| 9   | **Total Stunden** | `{{total_hours}}` |

The skill copies that row once per calendar day of the month and fills in:

* the **date label** (`Mo, 01.03.2027`) in the marker's own column, and
* the **hours** in the column immediately to its right.

Everything below the marker row — your total line, your signature block —
moves down to make room, keeping its formatting. Rows are copied with the
marker row's borders, fonts and colours, so style that one row the way you want
all day rows to look.

Rules of thumb:

* Use `{{day_rows}}` exactly **once** in the whole file. Twice is an error.
* Leave the cell to the right of the marker empty — that is where the hours go.
* Keep formulas that point *below* the marker row simple. Cell references are
  not re-written when rows are inserted, so prefer `{{total_hours}}` over a
  `SUM()` of the day rows.

## Where the skill looks for your template

In this order — the first one that exists wins:

1. `--template /path/to/file.xlsx`, if you pass it on this run;
2. `tally.xlsx` in the `templates` folder of your data folder — the "this is my
   normal template" spot;
3. the built-in default that ships with the skill
   (`assets/default-tally-template.xlsx`).

The result always reports which of the three was used, so there is never any
doubt about which document you are looking at.

## What you get

Every tally run writes:

* `<worker>-<month>-abrechnung.pdf` — the built-in PDF. **Always.** It does not
  depend on your template or on any other program being installed.
* `<worker>-<month>-abrechnung.xlsx` — your template, filled in.
* `<worker>-<month>-abrechnung-vorlage.pdf` — a PDF made *from your template*,
  but only if LibreOffice is installed on this computer. If it is not, the skill
  says so plainly; you can open the Excel file and print it to PDF yourself.

## When something is wrong with the template

The skill stops and tells you what to fix instead of guessing:

* **A placeholder is missing** — the message names it: "The template ... is
  missing the placeholder(s) `{{gross_pay}}`".
* **`{{day_rows}}` appears more than once** — the message lists the cells.
* **The file cannot be opened** (it is not really an `.xlsx`, or it is damaged)
  — the message says so and asks you to save it again from your spreadsheet
  program.

In all three cases nothing is written from the broken template. The built-in
PDF is not a substitute for your template, so you get the error, not a silent
fallback.

## Starting from the built-in template

The easiest way to make your own is to start from ours:

```bash
cp assets/default-tally-template.xlsx ~/.employee-timesheet/templates/tally.xlsx
```

Open it, move things around, add your logo, and keep the placeholders. It is
regenerated by `tools/make_default_tally_template.py`, so if you ever want to
see how it is built, that file is the readable source.
