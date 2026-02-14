---
name: run-plan
description: Sequentially execute .claude/tasks task files with a worker subagent then a reviewer subagent; stop on first failure
---

# Sequential Task Orchestration

You are the **overview orchestrator** running a sequential workflow for this repository only.

## Hard Constraints

- Task files live under `.claude/tasks/` in the current project
- Only **one subagent runs at a time**: always run subagents in the foreground so the main conversation blocks until they finish
- Subagents cannot spawn other subagents, so orchestration must happen here in the main conversation
- Do not edit product code while orchestrating. You may only write/edit files under `.claude/tasks/` and `.claude/artifacts/`

## Pre-Flight Checks

Stop and ask the user if any of these fail:

1. **Task index exists**: Ensure `.claude/tasks/task-index.md` exists
   - If missing: "Task index not found. Please run the plan decomposition step first using the plan-decomposer skill."

2. **Subagents exist**: Confirm both subagents are present in this project:
   - `.claude/agents/task-worker.md`
   - `.claude/agents/task-reviewer.md`
   - If missing: "Required subagents not found. Please create task-worker and task-reviewer in .claude/agents/."

3. **Artifacts directory exists**: Ensure `.claude/artifacts/` exists
   - Create it if missing (this is the only auto-fix allowed)

## Task Discovery and Ordering

### Step 1: Read Task Index
Read `.claude/tasks/task-index.md` to get the ordered list of task files.

### Step 2: Parse Task Files
For each task file path in the index:
1. Read the file
2. Find the STATUS line (must be one of these exact strings):
   - `STATUS: TODO`
   - `STATUS: DONE`
   - `STATUS: BLOCKED`
3. If STATUS is missing or uses any other value, stop and report the error to the user

### Step 3: Build Execution Queue
Create a list of tasks in index order, each with:
- File path
- Task ID (extracted from filename, e.g., "task-001")
- Current status
- Task title

## Execution Loop (Sequential, Stop-on-Failure)

For each task in order:

### If STATUS: DONE
- Skip this task
- Log: "Task {id} already complete, skipping."
- Continue to next task

### If STATUS: BLOCKED
- Stop immediately
- Report to user: "Task {id} is BLOCKED. Review `.claude/tasks/{filename}` for blocking issue."
- Ask user what to do next
- Do not proceed to remaining tasks

### If STATUS: TODO
Execute the following steps **strictly in order**:

#### A) Worker Step (Foreground Subagent)
1. Log: "Starting task-worker on task {id}..."
2. Invoke the `task-worker` subagent with this prompt:
   ```
   Work on this task file only: .claude/tasks/{filename}

   Read the task, implement the changes, run the tests, and update the task file with STATUS: DONE or STATUS: BLOCKED.

   Write your work report to: .claude/artifacts/{task-id}-work.md
   ```
3. **Wait for the subagent to complete** (foreground = blocking)
4. Log: "Worker completed task {id}"

#### B) Reviewer Step (Foreground Subagent)
1. Log: "Starting task-reviewer on task {id}..."
2. Invoke the `task-reviewer` subagent with this prompt:
   ```
   Review this completed task: .claude/tasks/{filename}

   Read the task file and the worker artifact at .claude/artifacts/{task-id}-work.md.

   Inspect the changes, re-run the tests, and write your review verdict to:
   .claude/artifacts/{task-id}-review.json

   Use this exact JSON format:
   {
     "task_id": "{task-id}",
     "verdict": "PASS" or "FAIL",
     "issues": ["specific issue 1", "specific issue 2"],
     "recommended_next_step": "..."
   }
   ```
3. **Wait for the reviewer to complete** (foreground = blocking)
4. Log: "Reviewer completed task {id}"

#### C) Gate (Pass/Fail Decision)
1. Read `.claude/artifacts/{task-id}-review.json`
2. Parse the JSON (if malformed or missing, stop and report error)
3. Check the verdict:

**If verdict == "PASS":**
- Log: "Task {id} PASSED review"
- Continue to the next task in the queue

**If verdict == "FAIL":**
- Log: "Task {id} FAILED review"
- Display the issues array to the user
- Stop the entire orchestration run
- Report to user:
  ```
  Task {id} failed review. Issues found:
  - Issue 1
  - Issue 2

  Review details: .claude/artifacts/{task-id}-review.json
  Review task file: .claude/tasks/{filename}

  What would you like to do?
  1. Fix manually and re-run /run-plan
  2. Skip this task and continue (risky)
  3. Abort the plan
  ```
- Do NOT attempt automatic fixes
- Wait for user input

## Completion

Completion (archive only on full success):
- Only when all tasks are complete (no STATUS: TODO remains, and execution never hit FAIL/BLOCKED):
  1) Invoke `/archive-run` with no args.
  2) After it finishes, report:
     - “All tasks completed successfully”
     - Archive run-id (from the archive manifest)
     - Archive locations:
       - `.claude/tasks/old/<run-id>/`
       - `.claude/artifacts/old/<run-id>/`
     - Manifest path:
       - `.claude/artifacts/old/<run-id>/archive-manifest.md`

Failure paths (do NOT archive):
- If any task is BLOCKED: stop and wait for user input; do not invoke `/archive-run`.
- If any review verdict is FAIL: stop and wait for user input; do not invoke `/archive-run`.
- If review JSON is missing/malformed: stop and wait for user input; do not invoke `/archive-run`.

When all tasks are either DONE or skipped:

```
Summary:
- Total tasks: {N}
- Completed: {done_count}
- Skipped (already done): {skip_count}
- Failed: 0

Artifacts generated in .claude/artifacts/:
- {task-id}-work.md (worker reports)
- {task-id}-review.json (review verdicts)
- subagent-log.txt (execution log)
```

## Error Handling

### Subagent Errors
If a subagent crashes or returns an error:
- Stop the orchestration
- Show the error to the user
- Ask how to proceed

### File System Errors
If you cannot read/write required files:
- Stop immediately
- Report the specific file and error
- Ask user to check permissions or file paths

### Timeout Handling
For very long-running subagents (>1 hour):
- The hooks in settings.local.json will notify the user
- You should wait patiently (do not timeout unless Claude Code itself times out)
- Trust that hooks are logging progress

## Logging

Log all major steps to help the user track progress:
- Task start/completion
- Worker invocations
- Reviewer invocations
- Pass/fail decisions
- Error conditions

Example log format:
```
[12:00:00] Starting orchestration run
[12:00:01] Found 5 tasks in queue
[12:00:02] Skipping task-001 (already DONE)
[12:00:03] Starting worker on task-002
[12:15:22] Worker completed task-002
[12:15:23] Starting reviewer on task-002
[12:18:45] Reviewer completed task-002
[12:18:46] Task-002 PASSED review
[12:18:47] Starting worker on task-003
...
```

## Best Practices

1. **Always run subagents in foreground** - Never use background mode
2. **Wait for completion** - Do not move to next step until subagent returns
3. **Stop on first failure** - Do not skip failed tasks or continue the queue
4. **Trust the subagents** - Do not second-guess their STATUS updates
5. **Be patient** - Local models may take 20-60 minutes per task
6. **Let hooks handle notifications** - You don't need to ping the user every minute