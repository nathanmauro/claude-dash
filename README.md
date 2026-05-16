# claude-dash

Local web dashboard for Claude Code sessions. Reads session logs from
`~/.claude/projects/` and shows all sessions grouped by project, with
tasks, token usage, and quick-action controls.

A React SPA (Vite + TanStack Query) backed by a FastAPI JSON API. The
indexer streams change events over Server-Sent Events so new sessions
appear without a page reload.

## Features

- Sessions grouped by project, filtered to a date window (default: today)
- Tasks with completion status; sessions with open tasks pinned to the top
- **Full-text search** across all session contents — SQLite FTS5 index,
  sub-millisecond results with highlighted snippets, inline panel
- **Live updates** — Server-Sent Events from the background indexer
  invalidate the dashboard query when new sessions are detected
- **Interactive icon row** on every project and session card:
  - 📂 Finder — opens the project directory
  - 🖥 Terminal — new Terminal window `cd`'d into the project
  - ⌨ Editor — opens in Cursor or VS Code
  - 🐙 GitHub — detects the remote URL from `.git/config` and opens the repo
  - 📝 Notion — deep-links to the associated Notion project
  - 🧠 Augment — shows local-index status; click to re-index
- Direction prompt on each session — submit to relaunch
  `claude --resume <id> "<prompt>"` in a new Terminal window
- Keyboard shortcuts: `/` focus filter, `Esc` clear, `←`/`→` shift one
  day, `t` today

## Architecture

```
claude_dash/
  config.py        constants (paths, port, launchd label)
  models.py        pydantic v2 models — Task, Session, UsageTotals,
                   NotionTodo, SearchResult, SubscriptionUsage, …
  parser.py        JSONL parser → Session
  db.py            SQLite schema + incremental FTS5 indexer + search
  indexer.py       background thread (60s interval) → publishes change events
  events.py        thread-safe asyncio fan-out (EventBus)
  notion.py        Notion API client + on-disk cache
  launcher.py      osascript/Terminal helpers + GitHub/Augment hooks
  subscription.py  /api/subscription-usage loader
  server.py        FastAPI app + uvicorn entry point (JSON API + SSE + SPA)
  __main__.py      `python -m claude_dash`
web/
  src/
    api.ts                 typed fetchers + types mirroring Pydantic models
    hooks/                 useDashboard, useTodos, useSearch,
                           useSubscription, useLiveIndex, useShortcuts,
                           useToast
    components/            TopBar, RangePicker, UsageBar, Sidebar,
                           NotionTodoGroup, NotionTodoItem, ProjectCard,
                           SessionCard, IconRow, GlobalSearch, Toaster
    pages/DashboardPage.tsx
    styles/                tokens.css + layout.css + components/*.css
    utils/format.ts        fmtTokens, fmtRange, fmtDuration, homeCollapse, …
  dist/                    built bundle (committed; no node needed at runtime)
```

The SQLite database lives at `~/.claude-dash/index.db`. On startup the
FastAPI app calls `db.init_db()` and `indexer.start()`, which runs
`db.index_all()` every 60 seconds, picking up only files whose `mtime`
or `size` has changed. Each indexer pass that touches sessions publishes
`{type: "indexed", sids: [...]}` to subscribers of `/api/events`.

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

The web bundle in `web/dist/` is committed, so the run flow does not
require node at runtime.

## Develop the UI

```
cd web
npm install
npm run dev      # vite dev server on :5173, /api proxied to :8765
```

Run the Python server in another terminal (`uv run claude-dash-server
--no-open`). Vite proxies `/api/*` to it, so the UI gets hot-reload
against the live backend.

## Build the UI

```
cd web
npm run build    # writes web/dist/
```

Commit `web/dist/` so end users don't need node installed.

## End-to-end tests

Playwright drives the SPA against `page.route('/api/**', …)` mocks — no
uvicorn, no `~/.claude/projects/*.jsonl`, and no Notion token required.
First time:

```
cd web
npx playwright install chromium
```

Then:

```
npm run test:e2e        # headless
npm run test:e2e:ui     # interactive runner
```

Specs live in `web/e2e/` and cover the range picker, Resume, SSE live
updates, global search, keyboard shortcuts, Notion refresh, responsive
breakpoint, and session collapsed-state persistence. Fixtures and the
default mocked API live in `web/e2e/fixtures.ts`.

## JSON API

| Method | Path | Notes |
|--------|------|-------|
| GET    | `/api/dashboard?from=&to=&date=` | sessions + projects + usage + project_index |
| GET    | `/api/todos`               | Notion todos + source + fetched_at |
| GET    | `/api/search?q=`           | FTS5 hits with highlighted snippets |
| GET    | `/api/subscription-usage`  | rate limits + cost |
| GET    | `/api/events`              | SSE — `{type:"indexed", sids:[...]}` |
| POST   | `/api/refresh-notion`      | `{ok}` |
| POST   | `/api/start`               | body `{cwd, prompt?}` |
| POST   | `/api/resume`              | body `{sid, cwd, prompt?}` |
| GET    | `/api/open-finder?cwd=`    | open in Finder |
| GET    | `/api/open-terminal?cwd=`  | new Terminal |
| GET    | `/api/open-editor?cwd=`    | Cursor / VS Code |
| GET    | `/api/augment-index?cwd=`  | trigger Augment indexing |

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

POST `/api/resume` runs an `osascript` that opens a new Terminal window
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
