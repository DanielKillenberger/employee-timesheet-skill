# Employee Timesheet Skill

A Claude Cowork / Claude Code Agent Skill for small-business employee timesheets.

## Intended capability

The first Flow Next specification covers:

- register a worker with name, recurring schedule, hourly pay, and currency;
- add month-specific off days and exceptional working days;
- generate a German monthly hours sheet as XLSX and print-ready PDF, with off days greyed;
- read a photo/scan of a filled sheet, validate the transcribed daily hours, total them, and calculate gross monthly pay from the worker's saved hourly rate;
- stop for human confirmation whenever handwriting or payroll input is ambiguous.

The repository has been initialized with Flow Next. Product code is intentionally not implemented before the specification and review lifecycle.

## Current state

- Flow Next copy-mode setup: complete
- Product specification: `.flow/specs/fn-1-monthly-employee-timesheet-skill.md`
- Implementation: pending plan/review/work

## Flow Next

```bash
.flow/bin/flowctl validate --all --json
.flow/bin/flowctl list
```

The complete lifecycle is:

```text
spec → plan → plan review → implementation → implementation review → QA
```

## Claude Cowork packaging target

The final skill will follow Anthropic's Agent Skills structure:

```text
employee-timesheet/
├── SKILL.md
├── scripts/
├── references/
└── assets/
```

A release ZIP will contain only runtime skill files. Employee records, pay rates, completed-sheet photos, `.git`, `.flow`, tests, and caches must not be packaged.

## Privacy and payroll boundary

This tool calculates a transparent **gross** amount from confirmed hours × registered hourly rate. It is not payroll, tax, social-insurance, overtime, holiday, or employment-law software. Real employee information remains local and must never be committed to this public repository.

## Source references

- [Anthropic Agent Skills repository](https://github.com/anthropics/skills)
- [Claude custom skills help](https://support.claude.com/en/articles/12512198-creating-custom-skills)
- [Claude skills documentation](https://code.claude.com/docs/en/skills)
