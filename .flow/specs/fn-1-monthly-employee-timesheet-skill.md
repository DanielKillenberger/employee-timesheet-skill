# fn-1-monthly-employee-timesheet-skill Monthly employee timesheet skill

## Goal & Context

Create a portable Claude Cowork skill for a small business to manage simple employee timesheets. The repository should be usable locally after cloning and should package cleanly for upload to Claude. The reference form is a German portrait A4 monthly sheet with every calendar day shown, non-working days greyed, blank hour-entry cells on scheduled days, and a total row.

The skill has two linked jobs:

1. Generate a blank monthly timesheet from a registered worker's schedule.
2. Read a photo or scan of a completed timesheet, calculate total hours, and calculate gross monthly pay from the worker's registered hourly rate.
3. After the hours are confirmed, generate a final-tally PDF suitable for sending to the employee.

The photo path is consequential payroll input. It must preserve uncertainty and require human confirmation when handwriting or worker identity is ambiguous; it must never silently invent hours.

## Decision Context

- A worker record consists of a stable ID, display name, recurring weekday schedule, hourly pay, currency, and optional month-specific off/extra-working dates.
- Default document language is German, matching the supplied reference form.
- Output should include editable XLSX and print-ready PDF.
- Hourly pay is gross hourly pay unless the user explicitly specifies a different meaning.
- Monthly pay is `confirmed total hours × registered hourly rate`; taxes, deductions, overtime premiums, holiday pay, and employer costs are out of scope unless explicitly added later.
- Worker records must stay in local user data, not be committed into the public skill repository.
- The repository is public and contains no real employee records or filled timesheet photos.
- The user may supply a template for the final tally document; when none is provided, a clean built-in layout is used. The monthly sheet always uses the built-in layout modeled on the German reference form.
- Currency is a plain text label (default `CHF`) attached to amounts; amounts themselves are stored as exact decimals and gross pay rounds to 2 decimal places.
- Generated final-tally documents contain personal pay data and belong in local output, never in git.
- The usability bar: a 50–60-year-old small-business owner (the bike-shop test) can install and use this skill without technical help, guided only by the README and Claude.

## Requirements

### R1 — Worker registration

The skill can register and update a worker with:

- stable worker ID;
- display name;
- normal working weekdays;
- hourly pay as an exact decimal amount;
- currency as a plain text label, default `CHF` (no code validation — it labels amounts, nothing more);
- optional month-specific off days and exceptional working days.

Re-registering schedule or pay preserves month overrides unless deliberately replaced. Money must use decimal arithmetic, not binary float.

### R2 — Monthly sheet generation

Given a registered worker ID and `YYYY-MM`, generate XLSX and PDF files that:

- contain every calendar date exactly once;
- show German weekday/date labels;
- grey the full row for every resolved off day;
- leave the hours field blank on working days;
- include a total-hours row;
- fit one portrait A4 page without clipping;
- handle leap years and all month lengths;
- do not print the hourly rate unless explicitly requested;
- use the built-in layout modeled on the reference form (sheet templates are out of scope; see R6 for the tally template).

### R3 — Filled-timesheet photo analysis

Given one or more photos/scans of a completed sheet and an explicit worker ID, the skill:

- reads the handwritten/typed daily hour entries;
- maps each value to the visible date;
- distinguishes blank, zero, and unreadable values;
- reports per-day extracted values and confidence/uncertainty;
- calculates a provisional total using only values it can read;
- explicitly lists ambiguous/missing entries and asks for confirmation before calling the result final;
- rejects duplicate dates, impossible dates, negative hours, and implausible daily hours pending confirmation;
- records the worker name observed on the sheet as a structured observation (`{kind: value|unreadable|not_provided, value?}`) with a computed match status against the registered display name (`matched`, `mismatch`, `unreadable`, `not_provided`); `mismatch` and `unreadable` block confirmation until explicitly accepted;
- uses the registered hourly rate and currency to calculate gross monthly pay only after the hours are confirmed;
- reports the arithmetic transparently: confirmed hours × hourly rate = gross pay;
- preserves the original image as evidence but never commits it to git.

The model's vision capability may perform transcription; deterministic bundled code must validate the structured entries and perform all totals/pay arithmetic.

### R4 — Local data and portability

- Repository follows the Agent Skills layout with a root `SKILL.md` and optional `scripts/`, `references/`, and `assets/`.
- Worker registry defaults to a local data directory outside the repository, configurable by argument/environment.
- No credentials or real employee/pay data ship in git.
- A packaging command creates an uploadable ZIP with the skill folder at the ZIP root containing `SKILL.md` and required resources (the layout Claude's skill upload accepts), excluding `.git`, `.flow`, tests, caches, and local data.
- Releases carry the packaged ZIP as a download asset (attached manually when cutting a version), so users grab one file instead of cloning and zipping.
- README documents clone/local use and the install path: download the Release ZIP → upload via Customize → Skills (works in regular chat and Cowork on all plans — noting that code execution must be enabled, with a plain-language troubleshooting step for accounts where it is off).
- The README installation guide is self-contained and step-by-step, written so that pasting the repository link into Claude (or another assistant) is enough for it to walk a non-technical user through the install — exact click paths, no assumed context.

### R5 — Final tally PDF for the employee

After the daily hours have been confirmed (R3), the skill generates a print-ready PDF addressed to the employee that:

- identifies the worker (display name), the month, and the generation date;
- lists the confirmed per-day hours;
- shows total confirmed hours, the hourly rate, the currency, and the resulting gross pay;
- states the arithmetic transparently: confirmed hours × hourly rate = gross pay;
- is written in German by default, consistent with the sheet language;
- uses the built-in layout (this mandatory PDF never depends on external converters); when a tally template is supplied, the template governs an ADDITIONAL filled XLSX version — and a templated PDF only where a converter is available (R6);
- is produced only from confirmed hours — never from provisional or ambiguous extractions;
- is saved to the local output directory and never committed to git.

The skill produces the file; sending it to the employee stays a human action.

### R6 — Tally template

- The user can provide a template for the final tally (R5) only — an XLSX file with placeholder cells; the placeholder convention is documented in the skill.
- Placeholders: `{{worker_name}}`, `{{month_title}}`, `{{generation_date}}`, `{{total_hours}}`, `{{rate}}`, `{{currency}}`, `{{gross_pay}}`, plus a `{{day_rows}}` marker row that is repeated per confirmed day (columns: date label, hours).
- Resolution order: per-invocation `--template PATH` > stored `templates/tally.xlsx` in the local data directory > bundled default (`assets/default-tally-template.xlsx`). Output reports which template was used.
- Contract: the tally ALWAYS produces the built-in PDF (R5's mandatory output, converter-free). The template governs the additional filled XLSX — and a templated PDF only when LibreOffice is available; the output JSON reports exactly which files were produced and why. "Honoring the template" (AC10) means the filled XLSX (and conditional templated PDF), never a silent substitute for them.
- When a template is missing required placeholders or is unreadable, the skill reports the specific problem (naming the placeholder) instead of silently falling back.

### R7 — Verification

Automated tests cover:

- registration and update behavior;
- exact decimal pay arithmetic, including the terminal-rounding rule (kaufmännisches Runden / ROUND_HALF_UP to 0.01) with boundary fixtures (e.g. half-cent cases);
- ordinary months, February, and leap years;
- recurring schedule plus monthly off/working overrides;
- grey-row count and XLSX total formula;
- structured photo-transcription validation, including ambiguity and impossible values;
- final-tally generation from confirmed entries, including refusal on unconfirmed input;
- tally-template application, including the missing-placeholder error path;
- package contents (skill folder at ZIP root) and absence of local data.

A generated representative sheet (XLSX + PDF) and tally receive structural checks plus a human eyeball pass against the reference form.

**Usability QA (the bike-shop test):** before release, one fresh-install walkthrough is performed following ONLY the README and SKILL.md as a non-technical user would — install the packaged ZIP into Claude, register a worker, generate a month, run the photo→confirm→tally flow. Every step must succeed without consulting the source code; friction found is fixed, not documented around.

## Boundaries

### In scope

- One worker per generated sheet.
- Recurring weekday schedules and explicit per-month exceptions.
- XLSX/PDF generation.
- Photo/scan transcription workflow with human confirmation for uncertainty.
- Gross pay calculation from total hours and registered hourly rate.
- Final-tally PDF generation for the employee after confirmation.
- User-supplied template for the final tally.
- Claude Cowork-compatible skill packaging and local use.

### Out of scope

- Payroll filing, tax, social-insurance, withholding, pension, overtime, holiday entitlement, sick leave, or legal compliance.
- Automatic payment or accounting-system posting.
- Sending the tally to the employee (email/chat delivery stays a human action).
- Face recognition or identifying a worker from appearance.
- Silent payroll decisions from low-confidence handwriting.
- Cloud database or SaaS backend.

## Acceptance Criteria

- **AC1:** A worker can be registered with name, weekday schedule, exact hourly pay, and currency, then read back without loss.
- **AC2:** Generating any requested month produces non-empty XLSX and one-page portrait A4 PDF with every date once and all resolved off days greyed.
- **AC3:** Month-specific off days and exceptional working days override the recurring schedule deterministically.
- **AC4:** Given confirmed structured daily entries, the tool computes exact total hours and gross pay using decimal arithmetic and emits a transparent receipt.
- **AC5:** Ambiguous, duplicate, negative, impossible, or implausible photo-derived entries prevent a final payroll result and are surfaced for confirmation.
- **AC6:** Tests pass for a 31-day month and leap-year February, including formatting/formula checks.
- **AC7:** The produced ZIP has the skill folder at the ZIP root containing a valid `SKILL.md` and all required scripts/resources, and no registry, real worker data, source photo, `.git`, or `.flow` content.
- **AC8:** README includes verified local setup, worker registration, monthly generation, filled-photo analysis, final-tally generation, template usage, and a self-contained step-by-step install guide (Release ZIP → Customize → Skills, exact click paths) that an assistant given only the repo link can relay to a non-technical user.
- **AC9:** After hours are confirmed, a final-tally PDF is generated with worker, month, per-day confirmed hours, total hours, rate, currency, and gross pay, and generation is refused while any entry is unconfirmed.
- **AC10:** A user-supplied tally template is honored, and an unusable template yields a specific error naming the problem rather than a silent fallback.
- **AC11:** A fresh-install usability walkthrough (install packaged ZIP → register → generate → photo → confirm → tally) succeeds following only the README and SKILL.md, with no step requiring technical knowledge beyond clicking and chatting.
## Quick commands

- `uv run pytest`
- `uv run scripts/timesheet.py --help`
- `uv run scripts/package_skill.py --output-dir dist`
- `.flow/bin/flowctl validate --all --json`

## References

- Supplied reference photo in the originating conversation (not committed because it may contain personal data).
- Anthropic Agent Skills repository and skill-creator structure: root `SKILL.md` with optional `scripts/`, `references/`, and `assets/`.
- Claude custom-skill documentation linked from README.

## Implementation approach

- Python 3.11+ (Claude's code-execution environment runs 3.11 — no 3.12-only syntax; `requires-python >= 3.11`), uv-managed (`pyproject.toml` at repo root). Runtime deps: `openpyxl` (XLSX), `reportlab` (PDF) — both pure-Python and preinstalled in Claude's code-execution environment (weasyprint rejected: native Pango/Cairo deps break portability). Dev group: `pytest`, `pypdf` (page-count checks).
- Repo root doubles as the skill folder: root `SKILL.md`, `scripts/`, `references/`, `assets/`. `scripts/package_skill.py` zips them under an `employee-timesheet/` folder at the ZIP root (the layout Claude's skill upload accepts). `.gitignore` gets an explicit exception so `assets/default-tally-template.xlsx` is tracked despite the global `*.xlsx` rule.
- One shared **month layout model** (pure module, no I/O): given worker record + `YYYY-MM`, emits per-date rows (date, German weekday/date label, working/off after schedule+override resolution). Both sheet renderers consume it — openpyxl for XLSX, reportlab for PDF. Two renderers, one source of truth; no XLSX→PDF conversion for the sheet.
- `scripts/timesheet.py` subcommands (`register`, `show`, `generate`, `validate-extraction`, `confirm`, `tally`, `export-data`, `import-data`) with `--json` output so Claude drives them deterministically. Claude performs vision transcription itself and feeds structured entries to `validate-extraction` via a documented JSON schema (per-day: date, kind `value|zero|blank|unreadable`, value, confidence, note); all validation and arithmetic is deterministic Python.
- Local data dir: default `~/.employee-timesheet/`, overridable via `TIMESHEET_DATA_DIR` env or `--data-dir`. Registry (`employees.json`), extraction sessions (`extractions/<worker>-<YYYY-MM>.json`), evidence photos (`filled-timesheets/`), templates (`templates/`), and generated documents (`output/`) live there. Scripts warn (JSON `warnings`) when the data dir resolves inside an ephemeral path (e.g. `/tmp`). SKILL.md tells Claude to confirm a persistent data location first (Cowork: a dedicated business-data folder OUTSIDE every git worktree — when the connected folder is a cloned repository, Claude asks the user to connect or create a separate folder, matching the script's git-worktree refusal; regular chat: use the `export-data`/`import-data` JSON bundle — REGISTRY ONLY, never sessions or photos, no absolute paths — which the user keeps between conversations; extraction is redone per conversation there, since the photo is at hand anyway). The AC11 walkthrough covers the repo-as-connected-folder path.
- Money and hours: `decimal.Decimal` from strings only, via strict finite grammars — hours `^\d{1,2}([.,]\d{1,2})?$` (max 2 fraction digits; MORE precision is an error surfaced for correction, never silently rounded; exponent notation, NaN, Infinity, signs rejected), rate `^\d{1,5}([.,]\d{1,4})?$`. German decimal comma normalized (single separator only). Hourly rate stored as a canonical dot-notation decimal string preserving scale, never quantized on storage. The monthly total is an exact sum; gross pay = total × rate, rounded ONCE at the end to 0.01 with ROUND_HALF_UP (kaufmännisches Runden). The tally receipt shows the unrounded product when rounding changed it, so the final number is auditable. Currency is a plain label string from the registry (default `CHF`).

## Plan decisions

1. **Confirmation state**: one session JSON per worker+month in the data dir, atomic writes, resumable. It holds an entry for every calendar date (kind `value|zero|blank|unreadable`, confidence, flags such as `implausible`) plus the evidence photo filenames + SHA-256 hashes. `validate-extraction` reports the provisional total (readable values only) and lists every entry needing attention. `confirm` accepts corrections (`--set DATE=HOURS`) and succeeds only when: no scheduled working day is left `blank`, EVERY `unreadable` entry — on working and off days alike — has been corrected or explicitly accepted, and no flag stands unaddressed (`--set` a corrected value or repeat the flagged value to accept it). Blank off-days are fine. On success it freezes the per-day set plus a snapshot of worker ID, name, rate, and currency — `tally` reads only that snapshot, so later re-registration never silently changes pay (snapshot immutability tested at the session layer in .3; end-to-end tally immutability in .4). Redoing extraction requires `--overwrite`.
2. **Deliberate replace** (R1): re-registration preserves month overrides unless `--replace-overrides` is passed.
3. **Precedence**: month overrides beat the weekday schedule; the same date as both off and extra in one registration is a validation error.
4. **No auto-accept** (R3): hours on the sheet count wherever they're written (off days included — reality wins over schedule), but nothing is final until the human confirms via Claude.
5. **Validation rules**: hours outside 0–24 hard-reject; above 12 flagged implausible; duplicate dates rejected; dates must exist in the target month (leap-aware); negative rejected; overrides outside their month rejected at registration; zero-working-day schedule allowed with a warning.
6. **Worker identity**: extraction always takes an explicit `--worker ID` (no name-based lookup). The entries JSON carries a structured `observed_name` object: `{kind: "value"|"unreadable"|"not_provided", value?: string}` (value required iff kind is `value`). The script computes match status — `matched`/`mismatch` from a case/whitespace-insensitive compare when kind is `value`; `unreadable`/`not_provided` pass through — and stores it in the session. `confirm` blocks on `mismatch` and `unreadable` until `--accept-identity` records the human's explicit go-ahead; `not_provided` does not block (sheets without a name line stay usable). All four statuses and their gates are tested.
7. **Worker ID + path safety**: IDs match `[a-z0-9][a-z0-9_-]{0,31}`; derived paths are resolved and asserted beneath the data dir; evidence filenames sanitized; data files created owner-only (0700/0600) where supported. The data dir must NOT sit inside a git worktree: resolution walks up for `.git` and refuses with a plain-language error (override `--allow-repo-data` for tests only) — payroll data never lands somewhere `git add` can reach. Repo `.gitignore` still adds defense-in-depth patterns for every local-data subtree (`data/`, `employees.json`, `extractions/`, `filled-timesheets/`, `output/`, `templates/`).
12. **Formula-injection safety**: every user-derived string written to a workbook (display name, currency label, notes, template substitutions) is forced to a literal string cell — formula cells are reserved for generated formulas like `SUM`. Adversarial values (leading `=`, `+`, `-`, `@`) are tested in both the monthly sheet and templated tally.
13. **Import validation**: `import-data` is transactional — the bundle version is checked and every record passes the same validators as registration (ID grammar, money grammar, weekday/override-date rules, conflict checks) BEFORE any write; one invalid record rejects the whole import with a specific error. Malformed IDs, money, dates, conflicts, duplicates, and unknown versions are tested.
8. **Script errors**: exit non-zero with JSON `{code, message, detail}`; Claude surfaces `message` verbatim.
9. **Tally template** (R6): XLSX with the placeholders listed in R6; `{{day_rows}}` marker row cloned per confirmed day. The built-in reportlab PDF is ALWAYS produced (R5's mandatory deliverable, no LibreOffice dependency); a template additionally yields a filled XLSX (+templated PDF via `soffice` only when available). Output JSON reports every file produced and notes when templated-PDF conversion was unavailable. Missing placeholder / unreadable file → specific JSON error naming the problem, never a silent fallback. Bundled default ships in `assets/` with a `.gitignore` exception.
10. **Transcription testing scope** (R7): pytest covers validation/arithmetic only — vision accuracy is Claude's; SKILL.md owns the conversational workflow.
11. **QA (the bike-shop test)**: structural pytest assertions (dates, grey rows, SUM formula, page setup, pdf page count) + one human eyeball pass of representative sheet/tally against `references/reference-layout.md` (privacy-safe structural description of the reference form) + the AC11 fresh-install walkthrough driven only by README/SKILL.md.

## Open questions (deferred)

- Worker deregistration flow — out of scope; IDs assumed stable.
- Non-German locales — German hardcoded; layout model keeps labels in one place for later i18n.
- Sheet templates and multi-currency support — deliberately dropped from v1 for simplicity.

## Early proof point

Task fn-1-monthly-employee-timesheet-skill.2 validates the core approach (shared layout model renders a one-page portrait A4 XLSX with correct grey rows and total formula — fit-to-page is the riskiest external behavior). If one-page fit cannot be made reliable, re-evaluate the layout strategy before the PDF/tally task builds on the same model.

## Requirement coverage

| Req | Description | Task(s) | Gap justification |
|------|-------------|---------|-------------------|
| AC1 | Worker registration round-trip | .1 | — |
| AC2 | Month generation XLSX + one-page A4 PDF | .2, .4 | — |
| AC3 | Deterministic override resolution | .1, .2 | — |
| AC4 | Exact totals + gross pay receipt (kaufm. Rundung) | .3 | — |
| AC5 | Ambiguous/invalid entries block final result | .3 | — |
| AC6 | 31-day + leap-February tests | .2, .3 | — |
| AC7 | ZIP layout + exclusions | .6 | — |
| AC8 | README incl. assistant-relayable install guide | .6 | — |
| AC9 | Tally only from confirmed hours | .3, .4 | — |
| AC10 | Tally template honored; specific errors | .4 | — |
| AC11 | Fresh-install usability walkthrough | .6 | — |
