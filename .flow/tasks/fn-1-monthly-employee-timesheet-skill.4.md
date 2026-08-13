# fn-1-monthly-employee-timesheet-skill.4 PDF rendering: monthly sheet + final tally

## Description
PDF sheet renderer, final tally generation (`tally`), and the tally template support.

**Size:** M
**Files:** `scripts/lib/pdf_sheet.py`, `scripts/lib/tally.py`, `scripts/timesheet.py` (tally + generate PDF half), `assets/default-tally-template.xlsx`, `references/templates.md`, `.gitignore` (template exception), `tests/test_pdf.py`, `tests/test_tally.py`

### Approach
- Sheet PDF: reportlab Table, A4 portrait, consuming the SAME layout model as task 2; grey off rows; total row; one page; rate omitted unless requested. Page count == 1 asserted via pypdf.
- `tally`: refuses (specific JSON error) unless session status is `confirmed`; reads ONLY the frozen snapshot from task 3. Content: worker name, month, generation date, per-day confirmed hours, total hours, rate, currency, gross pay, transparent arithmetic line (incl. unrounded product when rounding applied). German text.
- Tally ALWAYS produces the built-in reportlab PDF (R5 mandatory, no LibreOffice dependency; the template contract explicitly governs only the additional XLSX + conditional templated PDF).
- End-to-end snapshot test: re-register the worker after confirm; `tally` output unchanged (extends task 3's session-layer test).
- Formula-injection safety: user-derived strings in templated XLSX written as literal string cells; adversarial values tested. Tally template (R6): XLSX with placeholders `{{worker_name}}`, `{{month_title}}`, `{{generation_date}}`, `{{total_hours}}`, `{{rate}}`, `{{currency}}`, `{{gross_pay}}` and a `{{day_rows}}` marker row cloned per confirmed day (date label + hours columns, marker-row style copied). Resolution: `--template PATH` > data-dir `templates/tally.xlsx` > bundled default. A template ADDITIONALLY yields a filled XLSX (+templated PDF via `soffice` only when available); output JSON reports every file produced and notes when templated-PDF conversion was unavailable. Missing placeholder / unreadable file -> specific error naming the problem; never silent fallback.
- Bundled default template ships in `assets/`; add `.gitignore` exception (`!assets/default-tally-template.xlsx`) since `*.xlsx` is globally ignored — verify it is tracked.
- `references/templates.md`: placeholder convention + how to make your own template (bike-shop-owner-readable).

### Investigation targets
**Required**:
- `scripts/lib/layout.py` (task 2), `scripts/lib/extraction.py` + snapshot shape (task 3)
- `.flow/specs/fn-1-monthly-employee-timesheet-skill.md` — R5, R6, plan decision 9

### Key context
- reportlab tables: https://docs.reportlab.com/reportlab/userguide/ch7_tables/

### Acceptance
- [ ] Sheet PDF: every date once, grey off rows, 1 A4 page for 28-31-day months via pypdf (AC2)
- [ ] Tally refuses unconfirmed sessions (AC9); content complete from snapshot only
- [ ] Built-in PDF produced in ALL tally runs incl. templated ones (AC9/R5)
- [ ] User template honored; used-template reported; default template works out of the box (AC10)
- [ ] Missing-placeholder error names the placeholder; no silent fallback (AC10)
- [ ] Default template tracked in git despite *.xlsx ignore (test from clean file listing)
- [ ] Representative sheet PDF + tally eyeballed against checklist (evidence recorded)
## Acceptance
- [ ] AC9 refusal + snapshot-only content tests
- [ ] AC10 template positive + error paths
- [ ] pypdf page-count assertions
- [ ] .gitignore exception verified
- [ ] Eyeball evidence recorded
## Done summary
Monthly sheet PDF renderer (`lib/pdf_sheet.py`) sharing the task-2 layout model, so the XLSX and PDF can never disagree about dates or grey rows — one portrait A4 page asserted with pypdf for every month length, and Unicode text that either prints the employee's name correctly or refuses rather than drawing black boxes. Final tally (`lib/tally.py`): the built-in German PDF is produced unconditionally and converter-free from the frozen confirmation snapshot only, refuses any unconfirmed session (AC9), and re-derives the day set, total and pay receipt from the stored per-day hours so a hand-edited session can never dictate a payroll number or a path. A tally template (`{{...}}` placeholders plus a cloned `{{day_rows}}` marker row, resolved `--template` > data dir > bundled default, print areas and merges following the inserted rows) additionally yields a filled XLSX and, where LibreOffice exists, a separately named templated PDF; a missing placeholder, duplicate marker or unreadable file is a specific error, never a silent fallback (AC10). Sheet and tally documents were eyeballed against the checklist in `references/reference-layout.md`; placeholder contract documented in `references/templates.md`; the bundled default template is tracked despite the global `*.xlsx` ignore.
## Evidence
- Commits: b34053b90f0155c59a10eb6af27882c9e70bf5ee, 9883dfbe3beb3b6efc15ee61350fddc499cfa364, 81c85f4e580656f00bd5c329eb68af943dafa771, 7fc3d7dc39f9d716f6cbebe075aed396157d9d90
- Tests: uv run pytest (405 passed, 77 new for this task), uv run scripts/timesheet.py --help, .flow/bin/flowctl validate --all --json (0 errors), codex impl-review: SHIP after 3 fix rounds (7 findings, all fixed) - /tmp/impl-review-receipt-fn-1-monthly-employee-timesheet-skill.4.json
- PRs: