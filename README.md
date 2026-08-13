# Employee Timesheet Skill

A skill for Claude that runs the monthly hours cycle for a small business:
make the blank hours sheet, read the filled-in sheet back from a photo, check
the hours with you, and produce the final statement for your employee.

It calculates a **gross** amount: confirmed hours × your registered hourly rate.
It is not payroll, tax, social-insurance or employment-law software.

- Blank monthly sheet as Excel **and** a print-ready one-page A4 PDF, in German,
  with every day of the month listed and days off greyed out.
- Photo of the filled-in sheet is read by Claude and **checked with you** before
  anything is final — unreadable handwriting is never guessed.
- Final statement (Abrechnung) as PDF, optionally on your own Excel letterhead.
- Employee names, rates, photos and statements stay on your own machine.

---

## Install it into Claude (no technical knowledge needed)

You need: a Claude account, a web browser. Nothing else. Takes about 3 minutes.

**Step 1 — download the skill file.**

1. Open <https://github.com/DanielKillenberger/employee-timesheet-skill/releases>
   in your browser. (Or: on the project page click **Releases** in the right
   sidebar.)
2. The newest release is at the top. Under its **Assets** list, click
   **`employee-timesheet.zip`**. It downloads to your Downloads folder.
3. **Do not unzip it.** Claude wants the ZIP file exactly as it is. If your
   browser unpacked it automatically (Safari does this), see Troubleshooting
   below.

**Step 2 — upload it to Claude.**

1. Go to <https://claude.ai> and sign in.
2. Click your **initials or profile picture** in the bottom-left corner.
3. Click **Settings**.
4. In the list on the left, click **Capabilities** (on some accounts this is
   called **Customize**).
5. Find the **Skills** section and click it.
6. Click **Upload skill**.
7. Choose the `employee-timesheet.zip` file you just downloaded and confirm.
8. "Employee timesheet" now appears in your skills list with a switch next to
   it. Make sure the switch is **on**.

**Step 3 — check that code execution is on.** The skill makes real Excel and
PDF files, so Claude needs its code tool.

1. Still in **Settings → Capabilities**, look for **Code execution** (it may be
   called **Analysis tool** or **Code interpreter**).
2. Switch it **on** if it is off.

**Step 4 — try it.** Start a new chat and type:

> I want to set up a monthly hours sheet for my employee.

Claude takes it from there — it will ask for the name, the working days and the
hourly wage. You never have to type a command.

### Troubleshooting

| What you see | What to do |
| --- | --- |
| No **Skills** section in Settings | Skills are in **Capabilities** on most accounts and under **Customize** on others. If neither shows it, your Claude app may be out of date — reload the page. |
| The upload is rejected | You probably uploaded an unpacked folder or the wrong file. Download `employee-timesheet.zip` again and upload the ZIP itself, unopened. Safari users: in Safari → Settings → General, switch off "Open safe files after downloading", then download again. |
| Claude says it cannot run code | Turn on code execution (Step 3). Without it the skill cannot make Excel or PDF files. |
| Claude does not use the skill | Say it plainly: "Use the employee timesheet skill." Also check the switch next to the skill is on. |
| The files Claude makes disappear | In a normal chat, files live only for that conversation. Download them right away, and ask Claude for the "export bundle" at the end so your employee's record can be restored next time. In Cowork with a connected folder, files stay on your computer. |

### Where your data is kept

Ask Claude to keep everything in a **folder of your own** for business data,
for example `Timesheet-Data` in your home folder. Employee records, photos of
filled-in sheets and finished statements are written there — never into this
project folder, and never into the public repository. The skill actively refuses
to store payroll data inside a code folder.

---

## What you can ask Claude to do

| You say | What happens |
| --- | --- |
| "Register Anna, Monday to Friday, 28.50 CHF an hour." | The employee record is saved. |
| "Anna has 6 and 9 March off this month." | Those days are marked off for that month only. |
| "Make the sheet for March 2026." | Excel + one-page A4 PDF, days off greyed. Print the PDF. |
| *(upload a photo)* "Here is Anna's filled-in March sheet." | Claude reads it and shows you the days it could not read clearly. |
| "The 11th says 6 hours." | The correction is recorded. |
| "That is right, confirm it." | Hours are frozen; you get total hours × rate = gross pay. |
| "Make the statement for Anna." | The final PDF (and Excel) for your employee. |
| "Use my own letterhead for the statement." | Your Excel template is filled in — see [Templates](#your-own-statement-template). |
| "Give me my data to keep." | A small backup file with your employee records. |

Nothing is final until you say so. Anything Claude could not read clearly is
shown to you first — the total never includes a guess.

### Your own statement template

The final statement always comes as a clean built-in PDF. If you would rather
use your own layout, make an Excel file with placeholders like
`{{worker_name}}` and `{{gross_pay}}`, and tell Claude to use it. The full list
of placeholders is in [`references/templates.md`](references/templates.md).

---

## Data and privacy

- Employee records, photos and generated documents live in your local data
  folder (`~/.employee-timesheet` by default, or wherever you tell Claude).
- Nothing is uploaded anywhere by the skill, and nothing is committed to git.
  The scripts refuse a data folder inside a git project, and `.gitignore`
  blocks the same paths as a second line of defence.
- The repository is public and deliberately contains no real employee data and
  no filled-in sheet photos.
- Gross pay only: hours × rate. Tax, social insurance, overtime premiums,
  holiday pay and everything else is your accountant's business.

---

## Running it locally (developers)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone https://github.com/DanielKillenberger/employee-timesheet-skill.git
cd employee-timesheet-skill
uv sync

# never inside the repository — the script refuses that on purpose
export TIMESHEET_DATA_DIR=~/timesheet-data

uv run scripts/timesheet.py register --worker anna --name "Anna Muster" \
  --weekdays mon,tue,wed,thu,fri --rate 28.50 --currency CHF --json
uv run scripts/timesheet.py generate --worker anna --month 2026-03 --json
uv run scripts/timesheet.py validate-extraction --worker anna --month 2026-03 \
  --entries entries.json --photo sheet.jpg --json
uv run scripts/timesheet.py confirm --worker anna --month 2026-03 --set 2026-03-11=6 --json
uv run scripts/timesheet.py tally --worker anna --month 2026-03 --json
uv run scripts/timesheet.py export-data --output bundle.json --json
uv run scripts/timesheet.py import-data --input bundle.json --json
```

Every subcommand takes `--json` and `--data-dir`, and fails with
`{"code", "message", "detail"}` on stderr and a non-zero exit code.

```bash
uv run pytest                                  # full test suite
uv run scripts/timesheet.py --help
uv run scripts/package_skill.py --output-dir dist --json
```

Repository layout — the repository root *is* the skill folder:

```text
SKILL.md          instructions Claude reads
scripts/          timesheet.py + lib/ (the deterministic part)
references/       extraction schema, template placeholders, sheet layout
assets/           bundled default statement template
tests/            pytest suite (not packaged)
tools/            one-off generators (not packaged)
```

Documentation for skill authoring:
[Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
·
[Creating custom skills](https://support.claude.com/en/articles/12512198-creating-custom-skills)

### Cutting a release (maintainers)

```bash
uv run pytest
uv run scripts/package_skill.py --output-dir dist --json
```

`dist/employee-timesheet.zip` contains the `employee-timesheet/` folder at the
ZIP root with `SKILL.md`, `scripts/`, `references/` and `assets/` — tests in
`tests/test_packaging.py` enforce that layout and that no registry, photo,
generated document, `.git` or `.flow` content ever ships. Attach that ZIP to the
GitHub Release manually; the install guide above points users at it.
