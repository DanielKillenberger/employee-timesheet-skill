# Employee Timesheet Skill

## Repository state

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
- Independent reviewer: Codex/Sol.
- Preserve honest test failures and inspect generated PDF/XLSX artifacts visually.

<!-- BEGIN FLOW-NEXT -->
## Flow-Next

This project uses Flow-Next. Use `.flow/bin/flowctl` for ALL task tracking. Re-anchor by reading the spec and task status before every task.

```bash
.flow/bin/flowctl list
.flow/bin/flowctl show fn-N.M
.flow/bin/flowctl start fn-N.M
.flow/bin/flowctl done fn-N.M --summary-file summary.md --evidence-json evidence.json
```

Creating a spec: write it directly, then use `/flow-next:plan <spec-id>` for task breakdown. More: `.flow/bin/flowctl --help` or `.flow/usage.md`.
<!-- END FLOW-NEXT -->
