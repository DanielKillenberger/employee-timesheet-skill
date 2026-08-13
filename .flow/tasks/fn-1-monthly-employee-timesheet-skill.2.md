# fn-1-monthly-employee-timesheet-skill.2 Month layout model + XLSX generation

## Description
Shared month layout model + openpyxl XLSX renderer for the blank monthly sheet (`generate`, XLSX half; PDF in task 4).

**Size:** M
**Files:** `scripts/lib/layout.py`, `scripts/lib/xlsx_sheet.py`, `scripts/timesheet.py` (generate), `references/reference-layout.md`, `tests/test_layout.py`, `tests/test_xlsx.py`

### Approach
- `layout.py` (pure, no I/O): worker + `YYYY-MM` -> ordered per-date rows (date, German weekday/date label `Mo, 01.03.2027`, working/off after override precedence), German month title, all month lengths + leap Feb. Exposes schedule resolution for task 3.
- `xlsx_sheet.py`: header (name, month), one row per date, grey full row for off days (one reused PatternFill), blank hours on working days, `=SUM(...)` total row, rate omitted unless flag. All user-derived strings (name, currency) written as literal string cells — formula cells only for generated formulas; adversarial values (leading `=`, `+`, `-`, `@`) tested.
- A4 one page: BOTH `ws.sheet_properties.pageSetUpPr.fitToPage = True` AND `ws.page_setup` (portrait, A4, fitToWidth=1, fitToHeight=1) + explicit `print_area` (Excel ignores fit if only one side set).
- Output `output/<worker>-<YYYY-MM>.xlsx` in data dir.
- `references/reference-layout.md`: privacy-safe structural description of the reference form + the eyeball checklist (all dates visible, no clipped columns, one page, correct greys).

### Investigation targets
**Required**:
- `.flow/specs/fn-1-monthly-employee-timesheet-skill.md` — R2, plan decisions 3/11
- `scripts/lib/registry.py` — record shape from task 1

### Key context
- openpyxl print settings: https://openpyxl.readthedocs.io/en/stable/print_settings.html
- Early proof point: if one-page A4 fit is unreliable, stop and re-evaluate before task 4.

### Acceptance
- [ ] Every date exactly once for 28/29/30/31-day months (AC2, AC6)
- [ ] Grey rows == resolved off days; override precedence deterministic (AC3)
- [ ] Real SUM formula verified by reading the file back
- [ ] Page-setup fields asserted in tests
- [ ] Representative XLSX eyeballed against reference-layout.md checklist (evidence in task summary)
## Acceptance
- [ ] Layout tests: leap Feb, 31-day, precedence
- [ ] XLSX structure tests: dates, greys, SUM, page setup
- [ ] reference-layout.md + checklist written
- [ ] Eyeball evidence recorded
## Done summary
TBD

## Evidence
- Commits:
- Tests:
- PRs:
