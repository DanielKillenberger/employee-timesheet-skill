# fn-1-monthly-employee-timesheet-skill.6 SKILL.md, packaging, README + finalization

## Description
SKILL.md, packaging, README rewrite, and the fresh-install usability walkthrough (the bike-shop test).

**Size:** M
**Files:** `SKILL.md`, `scripts/package_skill.py`, `tests/test_packaging.py`, `README.md`, `CLAUDE.md` (state refresh)

### Approach
- `SKILL.md`: frontmatter `name` (lowercase-hyphens, <=64 chars, no "claude"/"anthropic" — e.g. `employee-timesheet`), `description` <=1024 chars stating what + when. Body under 5k tokens, written so Claude guides a non-technical user: workflows (register, generate, photo->validate->confirm->tally, tally template), the confirmation gate (never finalize unconfirmed hours; compare the name on the sheet with the registered name and ask when they differ), data location guidance (confirm a persistent data dir first; Cowork: a dedicated business-data folder OUTSIDE any git worktree — when the connected folder is a cloned repository, ask the user to connect/create a separate folder, matching the script's git-worktree refusal; regular chat: export-data/import-data registry bundle), required packages (openpyxl, reportlab — preinstalled), pointers to `references/templates.md` + `references/reference-layout.md` (one level deep). Scripts executed, not read.
- `package_skill.py --output-dir dist`: `employee-timesheet.zip`, skill folder at ZIP root with SKILL.md, scripts/, references/, assets/ (incl. default tally template); excludes `.git`, `.flow`, `tests/`, caches, local data.
- `tests/test_packaging.py`: unzip to temp; assert folder-at-root, SKILL.md frontmatter parses within limits, default template present, no forbidden content (employees.json, .git, .flow, output/, filled-timesheets/, *.zip).
- README rewrite: Installation section self-contained and step-by-step (download Release ZIP from GitHub Releases -> claude.ai -> Customize -> Skills -> Upload skill; works in regular chat and Cowork, all plans — noting code execution must be enabled, with a plain-language troubleshooting step when it is off; exact click paths, zero assumed knowledge — an assistant given only the repo link can relay it, AC8); Usage; Templates; Data & privacy; local dev (uv); maintainer note (package + attach ZIP to Release manually).
- Usability walkthrough (AC11): perform the full fresh-install flow following ONLY README + SKILL.md — install packaged ZIP, register a worker, generate a month, photo->confirm->tally with a sample filled sheet; include the repo-as-connected-folder path (skill must steer to a separate business-data folder). Record the transcript/evidence in the task summary; fix friction rather than documenting around it.
- Update CLAUDE.md "Repository state" (implementation landed; keep Flow-Next governance note).

### Investigation targets
**Required**:
- `.flow/specs/fn-1-monthly-employee-timesheet-skill.md` — R4, AC7/AC8/AC11
- Existing `README.md` — structure to extend
- All scripts/ modules — accurate usage docs

### Key context
- Skill authoring: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- ZIP layout (folder at root): https://support.claude.com/en/articles/12512198-creating-custom-skills

### Acceptance
- [ ] Packaging produces valid ZIP; tests enforce layout + exclusions + template presence (AC7)
- [ ] README install guide self-contained with exact click paths (AC8)
- [ ] SKILL.md within limits; documents workflows, confirmation gate, name-check, data-location guidance
- [ ] Fresh-install walkthrough performed and evidenced; frictions fixed (AC11)
- [ ] CLAUDE.md state refreshed
## Acceptance
- [ ] AC7/AC8 coverage
- [ ] ZIP inspected by tests
- [ ] AC11 walkthrough evidence recorded
## Done summary
TBD

## Evidence
- Commits:
- Tests:
- PRs:
