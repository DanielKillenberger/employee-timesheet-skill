# fn-1-monthly-employee-timesheet-skill.3 Extraction validation, confirmation state, pay arithmetic

## Description
Deterministic validation of transcribed entries, simple confirmation state, and pay arithmetic: `validate-extraction` and `confirm`.

**Size:** M
**Files:** `scripts/lib/extraction.py`, `scripts/lib/pay.py`, `scripts/timesheet.py` (subcommands), `tests/test_extraction.py`, `tests/test_pay.py`

### Approach
- Input contract: documented JSON schema on stdin/file — per day: `date`, `kind` (`value|zero|blank|unreadable`), `value`, `confidence` (`high|low`), optional `note`; top-level structured `observed_name` object. Claude transcribes the photo and produces this; the script validates. Test fixtures ship for the schema.
- Evidence: `--photo PATH...` copies images into `filled-timesheets/` (sanitized names) and records stored filename + SHA-256 in the session. Explicit `--worker ID` always (no name-based lookup).
- Identity gate: entries JSON carries structured `observed_name` `{kind: value|unreadable|not_provided, value?}` (value required iff kind=value); script computes match status (`matched|mismatch` via case/whitespace-insensitive compare; `unreadable|not_provided` pass through). `confirm` blocks on `mismatch`/`unreadable` until `--accept-identity`; `not_provided` never blocks. All four statuses + gates tested with provenance recorded.
- Validation: dates in month (leap-aware), no duplicates, 0-24 hard limits, >12 flagged implausible, negative rejected, decimal per money.py. Hours count wherever written — off-day values are valid (reality beats schedule).
- Session `extractions/<worker>-<YYYY-MM>.json`: every calendar date with kind/value/confidence/flags + evidence refs; status `extracted`; atomic; `--overwrite` to redo. Output: provisional total (readable only) + explicit list of entries needing attention (unreadable, blank-on-scheduled-day, implausible, low confidence).
- `confirm`: `--set DATE=HOURS` corrects (repeat flagged value to accept it); succeeds only when no scheduled working day remains blank, EVERY unreadable entry (working AND off days) is corrected or accepted, and no flag unaddressed; freezes per-day set + snapshot (worker id, name, rate, currency). Blank off-days fine. Refusals are specific JSON errors.
- `pay.py`: total = exact sum; gross = total x snapshot rate, rounded once (money.py rule); receipt shows hours, rate, currency, unrounded product when rounding changed it, final amount.

### Investigation targets
**Required**:
- `.flow/specs/fn-1-monthly-employee-timesheet-skill.md` — R3, plan decisions 1/4/5/6
- `scripts/lib/layout.py` — schedule resolution from task 2
- `scripts/lib/money.py`, `scripts/lib/datadir.py` — parsing, rounding, path helpers from task 1

### Key context
- Vision accuracy untestable; tests cover validation/arithmetic only (plan decision 10).

### Acceptance
- [ ] Duplicate/impossible/negative/implausible block confirmation with specific errors (AC5)
- [ ] Provisional total ignores unreadables; attention list complete
- [ ] Confirm refuses while scheduled blanks/unreadables/flags remain; --set works
- [ ] Snapshot immutability at the SESSION layer: post-confirmation re-registration leaves the frozen snapshot + pay receipt unchanged (end-to-end tally assertion lives in task 4)
- [ ] Pay exact incl. leap Feb + rounding boundary fixtures (AC4, AC6); receipt transparent
- [ ] Session resumable; --overwrite required to redo
## Acceptance
- [ ] AC4/AC5 coverage
- [ ] Entries-schema fixtures + strict validation tests
- [ ] Snapshot immutability test
- [ ] Session persistence + overwrite tests
## Done summary
Deterministic extraction validation, confirmation state and pay arithmetic: `lib/extraction.py` strictly validates the transcribed-entries document (hard rejection of duplicate, impossible and out-of-month dates, negative/over-precise/>24-hour values), flags every uncertain day (unreadable, blank working day, >12 h implausible, low confidence), computes the structured identity match, and keeps a resumable per-worker/month session holding every calendar date plus SHA-256-hashed evidence photos; `lib/pay.py` sums hours exactly and rounds gross pay once with ROUND_HALF_UP into a transparent receipt. `confirm` refuses while any working day is blank, any day is unreadable, any flag is unaddressed or the name on the sheet does not match, and freezes a worker snapshot on success — sessions are re-validated and their flags recomputed on load, so a truncated or hand-edited file can never confirm a short month or pay hidden hours. 121 new tests (328 total); reviewed by Codex (SHIP after two fix rounds).
## Evidence
- Commits: 0631873fe447371f0581def0cbcc8c836fddef90, f1981a0124b0d484a5c1b10cd12798b484ed3b27, e8eca8ae72e3d3f0c8d1704f20444a355925bd27
- Tests: uv run pytest (328 passed), uv run scripts/timesheet.py --help, .flow/bin/flowctl validate --all --json (0 errors), GATE_SKIPPED:unittest:green-receipt 536dc47f - baseline reused from prior post-gate pass
- PRs: