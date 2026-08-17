# Employee Timesheet Skill

## Repository state

The skill is implemented. The repository root *is* the skill folder: `SKILL.md`, `scripts/` (`timesheet.py` + `lib/`), `references/`, `assets/`; `tests/` and `tools/` stay out of the package. `scripts/package_skill.py --output-dir dist` builds the release ZIP (`employee-timesheet/` at the ZIP root), which is attached to a GitHub Release by hand.

This repository is governed by Flow Next. The approved specification is the source of truth. Do not implement product code during specification, planning, or review stages.

## Product boundaries

- Build a portable Claude Cowork skill, not a SaaS service.
- Keep employee records and filled timesheet images outside git.
- Use decimal arithmetic for hours and money.
- Photo extraction is provisional until ambiguous handwriting is confirmed.
- Monthly pay means gross confirmed hours × registered hourly rate; do not imply tax/payroll compliance.
- Package the runtime skill with root `SKILL.md` plus only required resources.

## Quality route

- Builder: Claude Opus 5, medium effort.
- Independent reviewer: Codex/Sol, high effort (plan and implementation reviews).
- Preserve honest test failures and inspect generated PDF/XLSX artifacts visually.

<!-- BEGIN FLOW-NEXT -->
<!-- flow-next:snippet:v1 -->
## Flow-Next

This project uses Flow-Next for ALL task tracking. `flowctl` comes from the flow-next plugin install — every flow-next skill resolves it itself, and on Claude Code it is also on PATH. Do NOT create markdown TODOs or use TodoWrite. Cold session: `flowctl brief` first — one bounded call (specs, ready tasks, memory); go deeper with `show`/`cat`/`anchor <task-id>`.

- Lifecycle: `flowctl list` / `show fn-N.M` / `start fn-N.M` / `done fn-N.M --summary-file s.md --evidence-json e.json` (e.json: `{"commits": ["<sha>"], "tests": ["<cmd>"], "prs": []}`)
- BEFORE any flowctl operation other than `brief`, or when unsure of a flag: run `flowctl usage` (CLI cheatsheet + orchestration recipes) or `flowctl --help`.
- BEFORE bridging work to another model/CLI (`codex exec`, `cursor-agent`, `claude -p`, `grok`) or picking an implementation/review model: run `flowctl usage` and follow "Orchestration & model steering" exactly.
- Creating a spec: write it directly — `/flow-next:plan` is task breakdown only. `flowctl spec create --title "Short title" --plan-file plan.md --json`, then `/flow-next:plan <spec-id>`. Scaffold cascade (first match wins): `SPEC.md` -> `spec.md` -> bundled template.
- If `flowctl` is not found: your shell lacks the plugin's `scripts/` dir on PATH (only Claude Code injects it). Resolve it the way the skills do - the plugin install's `scripts/flowctl` (Claude/Droid: plugin-root env var; Codex: `${CODEX_HOME:-$HOME/.codex}/scripts/flowctl`; Cursor/Grok: two levels above any flow-next SKILL.md) - or update/reinstall the flow-next plugin. A repo with no `.flow/` yet: run `/flow-next:setup`.
<!-- END FLOW-NEXT -->
