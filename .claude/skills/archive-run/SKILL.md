---
name: archive-run
description: Archive successful run artifacts and task files into .claude/**/old/<run-id>/ (project-scoped).
---

Archive the latest *successful* run by moving tasks and artifacts into `old/<run-id>/`.

Hard rules:
- Operate only within this repo’s `.claude/` directory.
- Do not modify product code.
- Do not delete; only move within `.claude/`.
- Do not move anything already under `.claude/**/old/`.

Run-id:
- If `$ARGUMENTS` is provided, use it verbatim (sanitize to `[A-Za-z0-9._-]` only; otherwise stop and ask user).
- Else generate: `YYYYMMDD-HHMMSS`.

Source sets:
A) Tasks (if present):
- `.claude/tasks/task-index.md`
- `.claude/tasks/task-*.md`

B) Artifacts (if present):
- `.claude/artifacts/*` (only files in the top of artifacts dir)
- Exclude `.claude/artifacts/old/**`

Destinations (create as needed):
- `.claude/tasks/old/<run-id>/`
- `.claude/artifacts/old/<run-id>/`

Steps:
1) Ensure destination dirs exist (`mkdir -p`).
2) Write manifest at `.claude/artifacts/old/<run-id>/archive-manifest.md` containing:
   - run-id + timestamp
   - list of task files moved
   - list of artifact files moved
   - any missing files/dirs encountered
3) Move tasks:
   - Move `task-index.md` if it exists.
   - Move all `task-*.md` files if any exist.
4) Move artifacts:
   - Move top-level `.claude/artifacts/*.json`, `*.md`, `*.txt`, `*.log` (whatever exists).
5) Recreate empty `.claude/tasks/` and `.claude/artifacts/` if they ended up missing after moves.
6) Confirm outcome: print the archive paths and manifest path.

If there is nothing to move (no tasks and no artifacts), stop and say “Nothing to archive.”
