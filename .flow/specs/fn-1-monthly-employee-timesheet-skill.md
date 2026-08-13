# fn-1-monthly-employee-timesheet-skill Monthly employee timesheet skill

## Goal & Context

Create a portable Claude Cowork skill for a small business to manage simple employee timesheets. The repository should be usable locally after cloning and should package cleanly for upload to Claude. The reference form is a German portrait A4 monthly sheet with every calendar day shown, non-working days greyed, blank hour-entry cells on scheduled days, and a total row.

The skill has two linked jobs:

1. Generate a blank monthly timesheet from a registered worker's schedule.
2. Read a photo or scan of a completed timesheet, calculate total hours, and calculate gross monthly pay from the worker's registered hourly rate.

The photo path is consequential payroll input. It must preserve uncertainty and require human confirmation when handwriting or worker identity is ambiguous; it must never silently invent hours.

## Decision Context

- A worker record consists of a stable ID, display name, recurring weekday schedule, hourly pay, currency, and optional month-specific off/extra-working dates.
- Default document language is German, matching the supplied reference form.
- Output should include editable XLSX and print-ready PDF.
- Hourly pay is gross hourly pay unless the user explicitly specifies a different meaning.
- Monthly pay is `confirmed total hours × registered hourly rate`; taxes, deductions, overtime premiums, holiday pay, and employer costs are out of scope unless explicitly added later.
- Worker records must stay in local user data, not be committed into the public skill repository.
- The repository is public and contains no real employee records or filled timesheet photos.

## Requirements

### R1 — Worker registration

The skill can register and update a worker with:

- stable worker ID;
- display name;
- normal working weekdays;
- hourly pay as an exact decimal amount;
- ISO 4217 currency code, default `CHF`;
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
- do not print the hourly rate unless explicitly requested.

### R3 — Filled-timesheet photo analysis

Given one or more photos/scans of a completed sheet and a worker ID (or an unambiguous worker name on the sheet), the skill:

- reads the handwritten/typed daily hour entries;
- maps each value to the visible date;
- distinguishes blank, zero, and unreadable values;
- reports per-day extracted values and confidence/uncertainty;
- calculates a provisional total using only values it can read;
- explicitly lists ambiguous/missing entries and asks for confirmation before calling the result final;
- rejects duplicate dates, impossible dates, negative hours, and implausible daily hours pending confirmation;
- uses the registered hourly rate and currency to calculate gross monthly pay only after the hours are confirmed;
- reports the arithmetic transparently: confirmed hours × hourly rate = gross pay;
- preserves the original image as evidence but never commits it to git.

The model's vision capability may perform transcription; deterministic bundled code must validate the structured entries and perform all totals/pay arithmetic.

### R4 — Local data and portability

- Repository follows the Agent Skills layout with a root `SKILL.md` and optional `scripts/`, `references/`, and `assets/`.
- Worker registry defaults to a local data directory outside the repository, configurable by argument/environment.
- No credentials or real employee/pay data ship in git.
- A packaging command creates an uploadable ZIP containing the skill and required resources, excluding `.git`, `.flow`, tests, caches, and local data.
- README documents clone/local use and Cowork custom-skill upload.

### R5 — Verification

Automated tests cover:

- registration and update behavior;
- exact decimal pay arithmetic;
- ordinary months, February, and leap years;
- recurring schedule plus monthly off/working overrides;
- grey-row count and XLSX total formula;
- structured photo-transcription validation, including ambiguity and impossible values;
- package contents and absence of local data.

A generated representative PDF and XLSX receive structural and visual QA against the supplied form.

## Boundaries

### In scope

- One worker per generated sheet.
- Recurring weekday schedules and explicit per-month exceptions.
- XLSX/PDF generation.
- Photo/scan transcription workflow with human confirmation for uncertainty.
- Gross pay calculation from total hours and registered hourly rate.
- Claude Cowork-compatible skill packaging and local use.

### Out of scope

- Payroll filing, tax, social-insurance, withholding, pension, overtime, holiday entitlement, sick leave, or legal compliance.
- Automatic payment or accounting-system posting.
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
- **AC7:** The produced ZIP has a valid root `SKILL.md`, all required scripts/resources, and no registry, real worker data, source photo, `.git`, or `.flow` content.
- **AC8:** README includes verified local setup, worker registration, monthly generation, filled-photo analysis, and Cowork upload instructions.

## Quick commands

- `uv run pytest`
- `uv run scripts/timesheet.py --help`
- `uv run scripts/package_skill.py --output-dir dist`
- `.flow/bin/flowctl validate --all --json`

## References

- Supplied reference photo in the originating conversation (not committed because it may contain personal data).
- Anthropic Agent Skills repository and skill-creator structure: root `SKILL.md` with optional `scripts/`, `references/`, and `assets/`.
- Claude custom-skill documentation linked from README.
