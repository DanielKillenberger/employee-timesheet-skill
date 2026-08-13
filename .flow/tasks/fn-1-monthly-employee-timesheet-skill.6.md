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
- [x] Packaging produces valid ZIP; tests enforce layout + exclusions + template presence (AC7)
- [x] README install guide self-contained with exact click paths (AC8)
- [x] SKILL.md within limits; documents workflows, confirmation gate, name-check, data-location guidance
- [x] Fresh-install walkthrough performed and evidenced; frictions fixed (AC11)
- [x] CLAUDE.md state refreshed
## Acceptance
- [x] AC7/AC8 coverage
- [x] ZIP inspected by tests
- [x] AC11 walkthrough evidence recorded

## AC11 fresh-install walkthrough (performed 2026-08-13)

The claude.ai upload itself cannot be automated from here, so the walkthrough
installed the **packaged release ZIP exactly as a user receives it** and then
drove the whole cycle from the extracted skill folder alone — plain `python3`,
no `uv`, no repository, no source reading, following only README + SKILL.md.

1. `package_skill.py --output-dir dist` → `dist/employee-timesheet.zip`;
   unzipped into an empty folder → single root folder `employee-timesheet/`
   with SKILL.md, scripts/, references/, assets/ (17 files).
2. Data folder chosen outside any git worktree, as SKILL.md step 0 instructs.
   The repo-as-connected-folder path was exercised: `--data-dir` inside the
   clone is refused with `data_dir_in_git_repo` in plain language, and
   `export-data` into the clone is refused with `export_into_git_repo`.
3. `register rolf` (Mo–Fr, 31.75 CHF, 2026-02-16 off) → record stored, umlaut
   name intact.
4. `generate 2026-02` → XLSX + PDF, 28 days, 19 working / 9 off.
5. Photo leg: transcription with one implausible day (13.5 h), one
   low-confidence day, a Saturday worked, and an abbreviated name
   ("R. Bäumler") → provisional total 161.5 h, identity `mismatch`,
   2 days flagged.
6. `confirm` without `--accept-identity` → refused (`identity_unconfirmed`).
   With the two `--set` decisions plus `--accept-identity` → confirmed,
   receipt `161.5 h x 31.75 CHF = 5127.63 CHF (exact 5127.625, rounded)`.
7. `tally` → built-in German PDF (1 page, umlaut correct, arithmetic and the
   gross-pay disclaimer printed) + filled XLSX from the **bundled** template
   resolved inside the extracted skill folder; the missing-LibreOffice note
   was reported calmly, not as a failure.
8. Regular-chat path: `export-data` → bundle → `import-data` into an empty
   second data folder → worker read back unchanged.

Friction found and **fixed** (not documented around):
- SKILL.md did not say where to run the script from → now states "from the
  folder that holds this SKILL.md, or use the full path".
- Nothing said where the transcribed-entries JSON belongs → now explicitly
  inside the data folder, never a code project.
- The export bundle example wrote into the clone, which the git guard refuses
  → README and SKILL.md now write the bundle into the data folder.
- Install click path corrected against Anthropic's current instructions
  (Customize → Skills → `+` → `+ Create skill` → Upload a skill; code
  execution enabled separately, with the Team/Enterprise owner step).
- Privacy wording corrected: files are local only in Cowork/local use; in a
  regular chat they live in Claude's temporary workspace.
## Done summary
TBD

## Evidence
- Commits:
- Tests:
- PRs:
