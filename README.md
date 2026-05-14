# claude-dash

Local web dashboard for Claude Code sessions. Reads session logs from
`~/.claude/projects/` and shows all sessions grouped by project, with
tasks, token usage, and quick-action controls.

## Features

- Sessions grouped by project, filtered to a date window (default: today)
- Tasks with completion status; sessions with open tasks pinned to the top
- **Full-text search** across all session contents — SQLite FTS5 index,
  sub-millisecond results with highlighted snippets
- **Interactive icon row** on every project and session card:
  - 📂 Finder — opens the project directory
  - 🖥 Terminal — new Terminal window `cd`'d into the project
  - ⌨ Editor — opens in Cursor or VS Code
  - 🐙 GitHub — detects the remote URL from `.git/config` and opens the repo
  - 📝 Notion — deep-links to the associated Notion project
  - 🧠 Augment — shows local-index status; click to re-index
- Direction prompt on each session — submit to relaunch
  `claude --resume <id> "<prompt>"` in a new Terminal window

## Architecture

```
dash.py         HTTP server, routing, HTML rendering
database.py     SQLite schema, incremental FTS5 indexer, search
parser.py       JSONL parser — produces Session and Task dataclasses
static/
  style.css     Design system (CSS custom properties, component styles)
  app.js        Filter, debounced global search, keyboard shortcuts
```

The SQLite database lives at `~/.claude-dash/index.db`. On startup the
server calls `init_db()` to create the schema, then a background thread
runs `index_all()` every 60 seconds, picking up only files whose `mtime`
or `size` has changed.

Search uses FTS5 `trigram` tokenizer (falls back to default tokenizer if
your SQLite build omits it) so partial-word matches work without special
syntax.

## Run

```
python3 dash.py
```

Server listens on `http://127.0.0.1:8765/` and opens the browser. Port
can be overridden with `CLAUDE_DASH_PORT`.

CLI listing (useful for verifying the index):

```
python3 dash.py --list                # today
python3 dash.py --list 2026-05-12     # specific day
```

## How the parser works

Each session is a JSONL file at
`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. The parser pulls:

- `ai-title` — rolling session title; last one wins
- `user` messages — top-level prompts only; skips sidechains, system
  reminders, command output
- `assistant` messages — indexed for search; token usage accumulated
- `tool_use` blocks for `TaskCreate` / `TaskUpdate` — registers and
  updates task status (`pending` / `in_progress` / `completed`)
- First and last timestamps for the time range

Incomplete tasks = anything not `completed` at end of file.

## Resume

POST to `/resume` runs an `osascript` that opens a new Terminal window
and executes `cd <cwd> && claude --resume <id> [prompt]`. The original
session stays untouched.

## launchd service

Install as a user LaunchAgent to keep the dashboard running in the
background and restart it on login. The plist should point at `dash.py`
with `--no-open` to skip the browser auto-launch.
