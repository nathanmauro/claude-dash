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
claude_dash/
  config.py        constants (paths, port, launchd label)
  models.py        pydantic v2 models — Task, Session, UsageTotals,
                   NotionTodo, SearchResult, SubscriptionUsage, …
  parser.py        JSONL parser → Session
  db.py            SQLite schema + incremental FTS5 indexer + search
  indexer.py       background thread (60s interval)
  notion.py        Notion API client + on-disk cache
  launcher.py      osascript/Terminal helpers + GitHub/Augment hooks
  views.py         render_session_card, render_icon_row, formatters
  render_todos.py  notion sidebar
  render_usage.py  usage header (today / 7d / range / rate limits)
  render_page.py   top-level page template
  server.py        FastAPI app + uvicorn entry point
  __main__.py      `python -m claude_dash`
static/
  style.css        Design system (CSS custom properties)
  app.js           Filter, debounced global search, keyboard shortcuts
```

The SQLite database lives at `~/.claude-dash/index.db`. On startup the
FastAPI app calls `db.init_db()` and `indexer.start()`, which runs
`db.index_all()` every 60 seconds, picking up only files whose `mtime`
or `size` has changed.

Search uses FTS5 `trigram` tokenizer (falls back to default tokenizer if
your SQLite build omits it) so partial-word matches work without special
syntax.

## Run

```
uv sync
uv run claude-dash-server
```

Server listens on `http://127.0.0.1:8765/` and opens the browser. Port
can be overridden with `CLAUDE_DASH_PORT`. Pass `--no-open` to skip the
browser launch.

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

```
bin/claude-dash install     # write & load LaunchAgent (RunAtLoad/KeepAlive)
bin/claude-dash status      # running via LaunchAgent (pid …) → URL
bin/claude-dash restart     # launchctl kickstart -k
bin/claude-dash stop        # launchctl bootout
bin/claude-dash uninstall   # remove the plist
bin/claude-dash logs        # tail -F ~/.claude-dash/claude-dash.log
```

The plist invokes `uv run claude-dash-server --no-open` with
`WorkingDirectory` set to the repo. Override the repo path with
`CLAUDE_DASH_REPO` or the `uv` binary with `CLAUDE_DASH_UV`.
