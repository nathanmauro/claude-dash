# claude-dash

Local web dashboard for Claude Code sessions. Reads session logs from
`~/.claude/projects/` and shows:

- All sessions on a given date (default: today), grouped by project
- Tasks created in each session, with completion status
- Sessions with open tasks pinned to the top of each project, marked
- A direction prompt box on each session — submit to relaunch
  `claude --resume <id> "<prompt>"` in a new Terminal window, in that
  session's original working directory

## Run

```
python3 dash.py
```

Server listens on `http://127.0.0.1:8765/` and opens the browser. Use
the date input or `?date=YYYY-MM-DD` to view any day.

CLI listing:

```
python3 dash.py --list                # today
python3 dash.py --list 2026-05-12     # specific day
```

## How it works

Each session is a JSONL file at
`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. The parser pulls:

- `ai-title` (rolling title; last one wins)
- `user` messages (top-level prompts only — skips sidechains, system
  reminders, command output)
- `assistant` `tool_use` blocks for `TaskCreate` / `TaskUpdate` —
  `TaskCreate` registers a task, `TaskUpdate` applies the latest status
  (`pending` / `in_progress` / `completed`)
- First and last timestamps for the time range

Incomplete tasks = anything not in `completed` at the end of the file.

## Resume button

POST to `/resume` runs an `osascript` that opens a new Terminal window
and executes `cd <cwd> && claude --resume <id> [prompt]`. The original
session stays untouched.
