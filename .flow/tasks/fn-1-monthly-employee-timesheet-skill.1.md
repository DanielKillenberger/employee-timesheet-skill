# fn-1-monthly-employee-timesheet-skill.1 Project scaffold + worker registry

## Description
Create the uv project scaffold and the worker registry: `register`, `show`, `export-data`, `import-data` subcommands.

**Size:** M
**Files:** `pyproject.toml`, `scripts/timesheet.py`, `scripts/lib/registry.py`, `scripts/lib/money.py`, `scripts/lib/datadir.py`, `tests/test_registry.py`, `tests/test_money.py`

### Approach
- uv project, `requires-python >= 3.11` (Claude's code-execution env runs 3.11 — no 3.12-only syntax). Runtime deps `openpyxl`, `reportlab`; dev group `pytest`, `pypdf`. `uv run pytest` and `uv run scripts/timesheet.py --help` must work after this task.
- Data dir (`datadir.py`): `--data-dir` > `TIMESHEET_DATA_DIR` > `~/.employee-timesheet/`; created on demand, owner-only perms (0700/0600) where supported; JSON `warnings` entry when it resolves inside an ephemeral path (`/tmp`). REFUSES a data dir inside a git worktree (walk up for `.git`; plain-language error; `--allow-repo-data` for tests only). Atomic writes (tmp+rename). Path-safety helper: derived paths resolved + asserted beneath the data dir. Extend repo `.gitignore` with defense-in-depth patterns for every local-data subtree (`extractions/`, `templates/` alongside existing entries).
- Worker ID grammar `[a-z0-9][a-z0-9_-]{0,31}`, validated with specific JSON error.
- Worker record: id, display name, working weekdays, hourly rate stored as canonical dot-notation decimal string preserving scale (`7,50` -> `7.50`; never quantized on storage), currency as plain label string (default `CHF`, no validation), month overrides `{YYYY-MM: {off: [...], extra: [...]}}`.
- `register` preserves month overrides unless `--replace-overrides`; same-date off+extra errors; override dates outside their month rejected (leap-aware); zero-working-day schedule allowed with warning.
- `money.py`: Decimal from strings only via strict finite grammars — hours `^\d{1,2}([.,]\d{1,2})?$` (excess precision is an error surfaced for correction, never silently rounded; exponent/NaN/Infinity/signs rejected), rate `^\d{1,5}([.,]\d{1,4})?$`. German comma normalized, single separator only (`7.5.5` rejected). Gross-pay rounding lives here: ROUND_HALF_UP to 0.01 (kaufmaennisches Runden), applied exactly once.
- `export-data`/`import-data`: versioned JSON bundle, REGISTRY ONLY (never sessions or photos, no absolute paths) — sessions stay local; on ephemeral surfaces extraction is redone per conversation. Import is transactional: version checked and EVERY record passes the same validators as registration (ID/money/weekday/override/conflict) before any write; one bad record rejects the whole bundle with a specific error. Refuses to clobber without `--force`. Malformed IDs/money/dates/conflicts/duplicates/unknown versions tested.
- All subcommands `--json`; errors exit non-zero with `{code, message, detail}`.

### Investigation targets
**Required**:
- `.flow/specs/fn-1-monthly-employee-timesheet-skill.md` — R1, plan decisions 1/2/3/5/7/8
- `.gitignore` — data file naming alignment
- `CLAUDE.md` — decimal + privacy constraints

### Key context
- Never construct `Decimal` from float.
- uv dependency groups: https://docs.astral.sh/uv/concepts/projects/dependencies/

### Acceptance
- [ ] `uv run pytest` green; CLI `--help` works
- [ ] Register -> read back: rate returns the canonical decimal string (AC1)
- [ ] Bad IDs (path chars, `..`, uppercase, >32) rejected; path containment tested
- [ ] Overrides preserved unless `--replace-overrides`; off+extra conflict errors
- [ ] Grammar tests: comma/dot, multi-separator, excess precision, exponent/NaN/Inf/sign rejection; ROUND_HALF_UP boundary fixtures (half-cent cases) pass
- [ ] Git-worktree data dir refused; gitignore covers all local-data subtrees
- [ ] export/import round-trip tested; ephemeral-dir warning fires for /tmp
## Acceptance
- [ ] AC1 round-trip (canonical rate string)
- [ ] ID grammar + path-safety tests
- [ ] Rounding rule boundary tests (kaufm. Rundung)
- [ ] Override preserve/replace tests
- [ ] Bundle export/import tests
## Done summary
TBD

## Evidence
- Commits:
- Tests:
- PRs:
