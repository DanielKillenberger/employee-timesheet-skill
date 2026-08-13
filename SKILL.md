---
name: employee-timesheet
description: Monthly employee timesheets for a small business - register a worker with weekday schedule and hourly rate, generate a blank German monthly hours sheet (XLSX + one-page A4 PDF), read a photo of the filled-in sheet, check the hours with the user, and produce a final tally document with total hours and gross pay. Use when the user talks about timesheets, hours sheets, Stundenrapport, Stundenzettel, monthly employee hours, an employee's working days or hourly wage, a photo of a filled-in hours sheet, or a monthly wage/pay statement (Abrechnung) for an employee. Not payroll, tax, or social-insurance software.
---

# Employee timesheet

Helps a small-business owner run the monthly hours cycle for one employee at a
time: make the sheet, hand it over, get it back filled in, check it together,
and produce the document that goes to the employee.

The user is usually **not technical**. Do the work for them: run the commands
yourself, never show a command line and never ask them to run one, and report
the result in plain sentences. Speak the user's language (German is common for
this workflow); the documents themselves are always German.

## The one rule that matters

**Never finalize hours the user has not confirmed.** Everything read from a
photo is provisional. Only after the user has looked at the days you list and
agreed may you confirm the month. The scripts enforce this — if a command
refuses, the refusal is correct; relay its message instead of working around it.

## Running the tools

All work goes through one script in this skill folder. Run it, never read it:

```bash
python3 scripts/timesheet.py <subcommand> --json --data-dir <DATA_DIR> ...
```

Run it from the skill folder — the folder that holds this `SKILL.md` — or give
the full path to `scripts/timesheet.py`. Always pass `--json`, and always pass
the data folder explicitly (see below).
Every command prints JSON. On failure the exit code is non-zero and the JSON is
`{"code": ..., "message": ..., "detail": ...}` — **relay `message` verbatim**,
translated if the user speaks another language. Do not invent a workaround.

Requires `openpyxl` and `reportlab` (already present in Claude's code execution
environment). If code execution is unavailable, say so plainly: the skill cannot
work without it, and the user has to enable it in their Claude settings.

## Step 0 — settle the data folder (do this first, once)

Worker records, sessions, photos and generated documents live in a **data
folder**. Pick it before anything else and reuse the same path all session.

- **Cowork / a connected folder:** use a dedicated business folder, e.g.
  `~/Timesheet-Data` or a folder inside the connected one — but **never inside a
  code repository**. If the connected folder is a cloned repository (it contains
  `.git`), ask the user to connect or create a separate folder for their
  employee data. The script refuses a data folder inside a git project; that
  refusal protects their payroll data from being published.
- **Regular chat (no persistent files):** files disappear when the conversation
  ends. Work in any folder for the conversation, and at the end run
  `export-data` and give the user the small bundle JSON to keep. Next time, ask
  for it back and run `import-data` first. The bundle holds worker records only
  — no photos, no sessions. Re-reading a photo next time is fine; the photo is
  at hand anyway.

If a command warns that the folder is temporary, tell the user, and offer the
export bundle.

## Workflow 1 — register a worker

Ask for: name, which weekdays they normally work, the gross hourly rate, and the
currency (default `CHF`). Then:

```bash
python3 scripts/timesheet.py register --worker anna --name "Anna Muster" \
  --weekdays mon,tue,wed,thu,fri --rate 28.50 --currency CHF \
  --data-dir <DATA_DIR> --json
```

- `--worker` is a short stable ID you choose: lowercase letters, digits, `-`,
  `_` (e.g. `anna`, `anna-m`). Reuse it forever for that person.
- Rate accepts `28.50` or `28,50`.
- Holidays or one-off changes for a single month:
  `--off 2026-03:2026-03-06,2026-03-09` and `--extra 2026-03:2026-03-07`.
- Re-registering keeps existing month exceptions unless `--replace-overrides`.

`show --worker anna` reads a worker back; `show` alone lists everyone.

## Workflow 2 — generate the blank monthly sheet

```bash
python3 scripts/timesheet.py generate --worker anna --month 2026-03 \
  --data-dir <DATA_DIR> --json
```

Produces an XLSX and a one-page A4 PDF listing every day of the month, with
non-working days greyed out and an empty hours column. Give the user both file
paths and say the PDF is the one to print. The hourly rate is **not** printed
unless they ask (`--include-rate`). `--force` replaces an existing sheet.

## Workflow 3 — filled-in sheet: photo → check → confirm → tally

This is the careful part. Four steps, in order.

### 3a. Read the photo (your job, not the script's)

Look at the photo yourself and transcribe it into a JSON file — one object per
day you can see. Full field reference: `references/extraction-schema.md`.

Write that file inside the data folder (or a scratch folder), never into the
skill folder or any code project: transcribed hours are payroll data too.

```json
{
  "schema_version": 1,
  "worker_id": "anna",
  "month": "2026-03",
  "observed_name": { "kind": "value", "value": "Anna Muster" },
  "entries": [
    { "date": "2026-03-02", "kind": "value", "value": "7.5", "confidence": "high" },
    { "date": "2026-03-03", "kind": "zero", "confidence": "high", "note": "krank" },
    { "date": "2026-03-04", "kind": "blank", "confidence": "high" },
    { "date": "2026-03-05", "kind": "unreadable", "confidence": "low" }
  ]
}
```

Be honest about what you see:

- `value` = hours are written (`"7,5"` is fine), `zero` = a written `0`,
  `blank` = the field is empty, `unreadable` = something is there but you cannot
  read it. **Guessing is the one unacceptable answer** — use `unreadable`.
- `confidence: "low"` whenever you are unsure. A low-confidence value is flagged
  for the user rather than silently believed.
- `observed_name` is the name written on the sheet, exactly as written. If there
  is no name line, use `{"kind": "not_provided"}`; if it is illegible,
  `{"kind": "unreadable"}`.
- Hours count wherever they are written, weekends included. Do not "fix" the
  sheet to match the schedule.

### 3b. Validate

```bash
python3 scripts/timesheet.py validate-extraction --worker anna --month 2026-03 \
  --entries entries.json --photo sheet.jpg --data-dir <DATA_DIR> --json
```

Pass `--photo` once per image so the original is kept as evidence. `--overwrite`
redoes an earlier reading of the same month.

The result gives a **provisional** total and a `needs_attention` list. Present
that list to the user in plain language, one line per day, e.g. "Mi, 11.03. — I
could not read the hours. What does it say?" Also report:

- `identity.status` — if it is `mismatch` or `unreadable`, **stop and ask**: the
  name on the sheet is not the registered name. Never assume a nickname.
  `not_provided` (no name line) is fine and does not block.
- any hard error: an impossible date, a duplicate day, negative hours or more
  than 24 h in a day is rejected outright. Re-read that spot on the photo.

Never present the provisional total as the amount to pay.

### 3c. Confirm (only after the user answers)

```bash
python3 scripts/timesheet.py confirm --worker anna --month 2026-03 \
  --set 2026-03-11=6 --set 2026-03-12=8 --data-dir <DATA_DIR> --json
```

- One `--set` per day the user decided; `--set DATE=0` for a day with no hours.
- To accept a flagged value as correct, repeat the same value with `--set`.
- If the name did not match and the user explicitly says the sheet is this
  worker's, add `--accept-identity` — only on their explicit say-so.

`confirm` succeeds only when nothing is left open. It returns the total hours
and the pay receipt: `total hours x rate = gross pay`. Read that arithmetic back
to the user. It is **gross** pay — no tax, no deductions, no overtime premium.
Say so if pay comes up.

The confirmed month is frozen together with the name, rate and currency, so a
later rate change never rewrites an old month.

### 3d. Final tally document

```bash
python3 scripts/timesheet.py tally --worker anna --month 2026-03 \
  --data-dir <DATA_DIR> --json
```

Always produces the built-in German PDF (`...-abrechnung.pdf`) plus a filled
XLSX from the template. `notes` may mention that no PDF could be made *from the
template* because LibreOffice is not installed — the built-in PDF is unaffected;
relay the note calmly. Hand the user the file paths. Sending the document to the
employee is their job, not yours.

## Workflow 4 — the user's own tally template

The user can supply their own Excel layout (letterhead, own wording) for the
tally. Placeholders and rules: `references/templates.md`. Use it with
`--template /path/to/file.xlsx`, or store it as `tally.xlsx` in the `templates`
folder of the data folder to make it the default. If a placeholder is missing or
the file is unreadable, the error names the exact problem — relay it; there is
deliberately no silent fallback.

## Keeping data between conversations

```bash
python3 scripts/timesheet.py export-data --output bundle.json --data-dir <DATA_DIR> --json
python3 scripts/timesheet.py import-data --input bundle.json --data-dir <DATA_DIR> --json
```

Export writes a small JSON with the worker records only. Import checks every
record before writing anything; `--force` overwrites workers that already exist.

## Boundaries

- Gross pay only: hours x rate. **Not** payroll, tax, social insurance,
  withholding, overtime, holiday entitlement or legal advice. If asked, say the
  skill does not do that and suggest their accountant.
- One worker per sheet and per month.
- Never commit or upload employee records, photos or tally documents anywhere.
- Never identify a person from a photograph; identity comes from the written
  name compared with the registered one.

## Reference files

- `references/extraction-schema.md` — the entries JSON in full.
- `references/templates.md` — tally template placeholders.
- `references/reference-layout.md` — what the monthly sheet looks like.
