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
- The skill sends employee data nowhere of its own: it only writes files where
  you tell it to. Where those files physically live depends on how you use
  Claude — see [Data and privacy](#data-and-privacy).

---

## Install it into Claude (no technical knowledge needed)

You need: a Claude account, a web browser. Nothing else. Takes about 3 minutes.

**Step 1 — download the skill file.**

1. Open <https://github.com/DanielKillenberger/employee-timesheet-skill/releases/latest>
   in your browser — it takes you straight to the newest release. (Or: on the
   project page click **Releases** in the right sidebar.)
2. Under the release's **Assets** list, click
   **`employee-timesheet.zip`**. It downloads to your Downloads folder.
3. **Do not unzip it.** Claude wants the ZIP file exactly as it is. If your
   browser unpacked it automatically (Safari does this), see Troubleshooting
   below.

**Step 2 — switch on code execution.** The skill makes real Excel and PDF
files, so Claude needs its code tool. Do this before uploading.

1. Go to <https://claude.ai> and sign in.
2. Click your **initials or profile picture** in the bottom-left corner, then
   click **Settings**.
3. Open **Capabilities** and switch on **Code execution and file creation**.
4. *Team or Enterprise account?* An owner must first switch on **Code execution
   and file creation** *and* **Skills** under **Organization settings →
   Skills**. If you cannot see those switches, ask whoever administers your
   Claude account to do it once.

**Step 3 — upload the skill.**

1. In the left sidebar of claude.ai, click **Customize**, then **Skills**.
2. Click the **`+`** button.
3. Click **`+ Create skill`**.
4. Choose **Upload a skill**.
5. Pick the `employee-timesheet.zip` file you downloaded and confirm.
6. "Employee timesheet" now appears in your skills list with a switch next to
   it. Make sure the switch is **on**.

**Step 4 — try it.** Start a new chat and type:

> I want to set up a monthly hours sheet for my employee.

Claude takes it from there — it will ask for the name, the working days and the
hourly wage. You never have to type a command.

### Troubleshooting

| What you see | What to do |
| --- | --- |
| No **Skills** entry under **Customize** | On a Team or Enterprise account an owner has to switch **Skills** on once under **Organization settings → Skills**. Otherwise reload the page — the app may be out of date. |
| The upload is rejected | You probably uploaded an unpacked folder or the wrong file. Download `employee-timesheet.zip` again and upload the ZIP itself, unopened. Safari users: in Safari → Settings → General, switch off "Open safe files after downloading", then download again. |
| Claude says it cannot run code | Turn on **Code execution and file creation** (Step 2). Without it the skill cannot make Excel or PDF files. |
| Claude does not use the skill | Say it plainly: "Use the employee timesheet skill." Also check the switch next to the skill is on. |
| The files Claude makes disappear | In a normal chat, files live only for that conversation. Download them right away, and ask Claude for the "export bundle" at the end so your employee's record can be restored next time. In Cowork with a connected folder, files stay on your computer. |

### Where your data is kept

Ask Claude to keep everything in a **folder of your own** for business data,
for example `Timesheet-Data`. Employee records, photos of filled-in sheets and
finished statements are written there — never into this project folder, and
never into the public repository; the skill refuses a data folder inside a code
project. Whether that folder is on *your computer* or inside Claude's temporary
workspace depends on how you use Claude — read
[Data and privacy](#data-and-privacy) before you start.

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

**Be clear-eyed about where the data goes.** There are three ways to run this
skill and they are not equally private:

| How you use it | Where the files land | What Claude sees |
| --- | --- | --- |
| **Cowork with a connected folder** | On your own computer, in the folder you connected | The photo you upload and what you type, as in any Claude conversation |
| **Regular claude.ai chat** | In Claude's temporary workspace for that conversation — they disappear afterwards, so download them | Same |
| **Locally from a terminal** (developers) | On your own computer only | Nothing — the scripts alone make no network calls at all |

In the first two cases you are using Claude normally: the photo of the sheet
and the employee's name, hours and rate are part of the conversation and are
processed by Anthropic under their usual terms. The skill itself adds no upload,
no analytics and no third party of its own. If that is not acceptable for your
employee data, use the local terminal route.

In every case:

- Nothing is committed to git. The scripts refuse a data folder — or an export
  bundle — inside a git project, and `.gitignore` blocks the same paths as a
  second line of defence.
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

# transcribed hours and photos are payroll data too: keep them out of the repo
uv run scripts/timesheet.py validate-extraction --worker anna --month 2026-03 \
  --entries "$TIMESHEET_DATA_DIR/entries.json" \
  --photo "$TIMESHEET_DATA_DIR/sheet.jpg" --json
uv run scripts/timesheet.py confirm --worker anna --month 2026-03 --set 2026-03-11=6 --json
uv run scripts/timesheet.py tally --worker anna --month 2026-03 --json
uv run scripts/timesheet.py export-data --output "$TIMESHEET_DATA_DIR/bundle.json" --json

# ...later, or on another machine: restore into an empty data folder
uv run scripts/timesheet.py import-data --input "$TIMESHEET_DATA_DIR/bundle.json" \
  --data-dir ~/timesheet-data-restored --json
```

`export-data` refuses to write inside a git worktree, so the bundle path must
be outside the clone — as above. `import-data` refuses to overwrite a worker
that is already registered; restore into an empty data folder, or pass
`--force` when you deliberately want the bundle to win.

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
