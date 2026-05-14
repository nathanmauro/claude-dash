# claude-dash Implementation Plan

## 1. Fast Full-Text Search (SQLite/FTS5)
Migrate session parsing from on-demand directory walks to a persistent SQLite database. This provides sub-millisecond page loads and complex search capabilities.

- **Schema**:
  - `sessions`: id, cwd, title, start_ts, end_ts, mtime, size, user_msg_count, tokens, etc.
  - `messages`: session_id, role, content, timestamp.
  - `messages_fts`: FTS5 virtual table for searching content.
- **Incremental Indexing**: Background thread walks `~/.claude/projects/`. Only parse files where `(mtime, size)` doesn't match the DB. For active sessions, read only the appended portion.
- **Search UI**: `/`-focused search bar. Returns ranked snippets with context highlighting.

## 2. Project Metadata & Association
Upgrade "Project" from a string (cwd) to a tracked entity in a `project_meta` table.

- **Auto-Detection**:
  - **Git**: Parse `.git/config` for origin URLs (GitHub/GitLab).
  - **Notion**: Store association between local path and Notion project page IDs.
  - **Editor**: Track preferred editor (`code`, `cursor`, `vim`).
- **Persistence**: Store metadata in `~/.claude-dash/dash.db`.

## 3. UI Icon Bar (Action Row)
Add a row of interactive icons to each project header and session card.

- **Icons & Actions**:
  - 📁 **Finder**: `open -R <cwd>`
  - 🖥 **Terminal**: Resume session in a new terminal window.
  - ⌨ **Editor**: Open project in preferred IDE.
  - 🐙 **GitHub**: Link to normalized remote URL.
  - 📝 **Notion**: Link to associated project/todo page.
  - 🧠 **Augment**: Status indicator (indexed/not) + trigger for local indexing.

## 4. Augment CLI Integration
Enable local indexing via Augment's CLI.
- Research specific CLI commands for triggering/checking local index status.
- Implement `POST /augment/index` to shell out and update `project_meta`.
- Add status polling to show indexing progress in the UI.

## 5. Architecture Refactor
- Split `dash.py` into `server.py`, `parser.py`, and `database.py`.
- Move HTML/CSS/JS out of f-strings and into a `static/` or `templates/` directory.
- Add basic unit tests for the JSONL parsing logic and task state reconciliation.
