#!/usr/bin/env python3
"""Claude Code session dashboard.

Reads ~/.claude/projects/<encoded-path>/<session-id>.jsonl and renders a
local web dashboard grouped by project. Highlights sessions with
incomplete tasks. Lets you relaunch any session (with an optional
direction prompt) in a new Terminal window.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import shlex
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import database
import parser as p
import threading

database.init_db()

import time

PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Background indexer
def start_indexer():
    while True:
        try:
            database.index_all(PROJECTS_DIR)
        except Exception as e:
            print(f"Indexer error: {e}")
        time.sleep(60)

threading.Thread(target=start_indexer, daemon=True).start()
PORT = int(os.environ.get("CLAUDE_DASH_PORT", "8765"))
DASH_CACHE = Path.home() / ".claude-dash"
NOTION_CACHE_FILE = DASH_CACHE / "notion-todos.json"
USAGE_FILE = DASH_CACHE / "usage.json"
NOTION_DB_ID = os.environ.get(
    "TODO_NOTION_DB_ID", "353b9be9-bd58-8049-b5c5-e577f0a49756"
)
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
KEYCHAIN_ACCOUNT = "notion"
def get_github_url(cwd: str) -> str | None:
    config = Path(cwd) / ".git" / "config"
    if not config.exists():
        return None
    try:
        content = config.read_text()
        for line in content.splitlines():
            if "url =" in line:
                url = line.split("=")[1].strip()
                if url.startswith("git@github.com:"):
                    return "https://github.com/" + url[15:].replace(".git", "")
                if url.startswith("https://github.com/"):
                    return url.replace(".git", "")
    except Exception:
        pass
    return None

def get_notion_project_url(project_name: str) -> str:
    # Fallback to searching Notion by project name if we don't have the specific page ID
    return f"https://www.notion.so/search?q={urllib.parse.quote(project_name)}"

def get_augment_status(cwd: str) -> str:
    with database.get_db() as conn:
        row = conn.execute("SELECT augment_indexed_at FROM project_meta WHERE cwd = ?", (cwd,)).fetchone()
        if row and row['augment_indexed_at']:
            return f"indexed at {row['augment_indexed_at'][:16]}"
    if (Path(cwd) / ".augment").exists():
        return "indexed"
    return "not indexed"

KEYCHAIN_SERVICE = "todo-cli"

def render_icon_row(cwd: str, project_name: str) -> str:
    gh_url = get_github_url(cwd)
    notion_url = get_notion_project_url(project_name)
    aug_status = get_augment_status(cwd)

    icons = []

    # Finder
    icons.append(f'''
        <a class="icon-btn" href="/open-finder?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
            <span class="tooltip">Finder: {html.escape(_home_collapse(cwd))}</span>
        </a>
    ''')

    # Terminal
    icons.append(f'''
        <a class="icon-btn" href="/open-terminal?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
            <span class="tooltip">Terminal</span>
        </a>
    ''')

    # Editor (Cursor/VSCode)
    icons.append(f'''
        <a class="icon-btn" href="/open-editor?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/></svg>
            <span class="tooltip">Editor (Cursor)</span>
        </a>
    ''')

    # GitHub
    if gh_url:
        icons.append(f'''
            <a class="icon-btn" href="{gh_url}" target="_blank">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></svg>
                <span class="tooltip">GitHub: {html.escape(gh_url.split('/')[-1])}</span>
            </a>
        ''')

    # Notion
    icons.append(f'''
        <a class="icon-btn" href="{notion_url}" target="_blank">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/><line x1="9" y1="11" x2="15" y2="11"/><line x1="9" y1="19" x2="13" y2="19"/></svg>
            <span class="tooltip">Notion Project</span>
        </a>
    ''')

    # Augment
    aug_cls = "ok" if aug_status == "indexed" else ""
    icons.append(f'''
        <a class="icon-btn {aug_cls}" href="/augment/index?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/><path d="M12 6v6l4 2"/></svg>
            <span class="tooltip">Augment: {aug_status} (Click to index)</span>
        </a>
    ''')

    return f'<div class="icon-row">{"".join(icons)}<iframe name="hidden-frame" style="display:none"></iframe></div>'


def load_sessions(on_date=None, since: dt.date | None = None, until: dt.date | None = None):
    """Query sessions from SQLite."""
    with database.get_db() as conn:
        q = "SELECT * FROM sessions"
        params = []
        if on_date:
            q += " WHERE date(start_ts) = ?"
            params.append(on_date.isoformat())
        elif since or until:
            q += " WHERE 1=1"
            if since:
                q += " AND date(end_ts) >= ?"
                params.append(since.isoformat())
            if until:
                q += " AND date(end_ts) <= ?"
                params.append(until.isoformat())

        q += " ORDER BY end_ts DESC"
        rows = conn.execute(q, params).fetchall()

        sessions = []
        for r in rows:
            sid = r['session_id']
            # Load tasks for this session
            task_rows = conn.execute("SELECT * FROM tasks WHERE session_id = ?", (sid,)).fetchall()
            tasks = {tr['task_id']: p.Task(tr['task_id'], tr['subject'], tr['description'], tr['status']) for tr in task_rows}

            sessions.append(p.Session(
                session_id=sid,
                project_dir=r['project_dir'],
                cwd=r['cwd'],
                path=Path(PROJECTS_DIR) / r['project_dir'] / f"{sid}.jsonl",
                start_ts=p.parse_ts(r['start_ts']),
                end_ts=p.parse_ts(r['end_ts']),
                title=r['title'],
                first_prompt=r['first_prompt'],
                last_prompt=r['last_prompt'],
                tasks=tasks,
                user_msg_count=r['user_msg_count'],
                input_tokens=r['input_tokens'],
                output_tokens=r['output_tokens'],
                cache_create_tokens=r['cache_create_tokens'],
                cache_read_tokens=r['cache_read_tokens']
            ))
        return sessions


def build_project_index(sessions):
    """{lowercased key: (cwd, latest_session_id)} for both full cwd and basename(cwd).
    Expects sessions newest-first; first hit per key wins (so latest session)."""
    idx = {}
    for s in sessions:
        cwd = s.cwd
        base = Path(cwd).name
        for key in (cwd.lower(), base.lower()):
            if key and key not in idx:
                idx[key] = (cwd, s.session_id)
    return idx


def notion_token() -> str | None:
    env = os.environ.get("NOTION_TOKEN")
    if env:
        return env
    try:
        r = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                KEYCHAIN_ACCOUNT,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _notion_prop_text(props: dict, name: str) -> str:
    """Extract a string from a Notion property regardless of underlying type."""
    p = props.get(name) or {}
    if p.get("select"):
        return p["select"].get("name") or ""
    if p.get("multi_select"):
        return ", ".join(x.get("name", "") for x in p["multi_select"] if x.get("name"))
    if p.get("status"):
        return p["status"].get("name") or ""
    if p.get("rich_text"):
        return "".join(x.get("plain_text", "") for x in p["rich_text"])
    if p.get("title"):
        return "".join(x.get("plain_text", "") for x in p["title"])
    if p.get("people"):
        first = p["people"][0]
        return first.get("name") or first.get("id") or ""
    return ""


def fetch_notion_todos_live(tok: str) -> list[dict] | None:
    """POST <db>/query, filter to non-Done. Returns minimal todo dicts."""
    import urllib.request, urllib.error

    body = {
        "filter": {
            "or": [
                {"property": "Status", "status": {"equals": "Not started"}},
                {"property": "Status", "status": {"equals": "In progress"}},
            ]
        },
        "sorts": [{"property": "Due date", "direction": "ascending"}],
        "page_size": 100,
    }
    req = urllib.request.Request(
        f"{NOTION_API}/data_sources/{NOTION_DB_ID}/query",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {tok}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        # fallback path: classic databases endpoint
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{NOTION_DB_ID}/query",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {tok}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return None
    todos = []
    for r in data.get("results", []):
        props = r.get("properties", {}) or {}
        title_prop = props.get("Task name", {}) or {}
        title_arr = title_prop.get("title", []) or []
        name = "".join(t.get("plain_text", "") for t in title_arr)
        status_prop = (props.get("Status", {}) or {}).get("status") or {}
        status = status_prop.get("name", "")
        due_prop = (props.get("Due date", {}) or {}).get("date") or {}
        due = due_prop.get("start")
        project = _notion_prop_text(props, "Project")
        source = _notion_prop_text(props, "Source")
        todos.append({
            "name": name, "status": status, "due": due, "url": r.get("url"),
            "project": project, "source": source,
        })
    return todos


def load_notion_todos() -> tuple[list[dict], str, str | None]:
    """(todos, source, error). Source = live | cache | none."""
    tok = notion_token()
    if tok:
        live = fetch_notion_todos_live(tok)
        if live is not None:
            return live, "live", None
    if NOTION_CACHE_FILE.exists():
        try:
            data = json.loads(NOTION_CACHE_FILE.read_text())
            return data.get("todos", []), "cache", data.get("fetched_at")
        except (OSError, json.JSONDecodeError):
            pass
    return [], "none", None


def usage_totals(sessions: list[Session]) -> dict:
    inp = sum(s.input_tokens for s in sessions)
    out = sum(s.output_tokens for s in sessions)
    cc = sum(s.cache_create_tokens for s in sessions)
    cr = sum(s.cache_read_tokens for s in sessions)
    return {
        "input": inp,
        "output": out,
        "cache_create": cc,
        "cache_read": cr,
        "billable": inp + out + cc,
        "total": inp + out + cc + cr,
        "cache_hit_pct": (100.0 * cr / max(1, cr + cc + inp)) if (cr or cc or inp) else 0.0,
        "session_count": len(sessions),
    }


def load_subscription_usage() -> dict | None:
    """Read the rate_limits snapshot captured by the statusline hook."""
    if not USAGE_FILE.exists():
        return None
    try:
        data = json.loads(USAGE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_local(ts):
    if not ts:
        return ""
    return ts.astimezone().strftime("%H:%M")


def fmt_range(start, end):
    if not start or not end:
        return ""
    s = start.astimezone()
    e = end.astimezone()
    if s.date() == e.date():
        return f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
    return f"{s.strftime('%b %d %H:%M')} → {e.strftime('%b %d %H:%M')}"


def fmt_duration(start, end):
    if not start or not end:
        return ""
    secs = int((end - start).total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    return f"{mins // 60}h {mins % 60}m"


def truncate(s: str, n: int = 180) -> str:
    s = s.strip().replace("\n", " ")
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


STATUS_LABEL = {
    "completed": "done",
    "in_progress": "in-prog",
    "pending": "todo",
}


def render_session_card(s: Session) -> str:
    incomplete = s.incomplete_tasks
    completed = s.completed_tasks
    pill = ""
    if incomplete:
        pill = (
            f'<span class="pill warn">{len(incomplete)} open task'
            f'{"s" if len(incomplete) != 1 else ""}</span>'
        )
    elif s.tasks:
        pill = f'<span class="pill ok">{len(completed)} done</span>'

    task_rows = []
    for task in s.tasks.values():
        label = STATUS_LABEL.get(task.status, task.status)
        task_rows.append(
            f'<li><span class="status {html.escape(task.status)}">{html.escape(label)}</span>'
            f'<span class="subject">{html.escape(task.subject)}</span></li>'
        )
    tasks_html = (
        f'<ul class="tasks">{"".join(task_rows)}</ul>'
        if task_rows
        else '<p class="muted">No tracked tasks.</p>'
    )

    search_blob = " ".join(filter(None, [
        s.title, s.first_prompt, s.last_prompt, s.cwd, s.session_id,
        " ".join(t.subject for t in s.tasks.values()),
    ])).lower()

    first = (
        html.escape(truncate(s.first_prompt, 220))
        if s.first_prompt
        else '<span class="muted">(no user prompt)</span>'
    )
    last = html.escape(truncate(s.last_prompt, 220)) if s.last_prompt else ""

    title = html.escape(s.title or s.first_prompt[:80] or s.session_id)
    has_incomplete = "warn" if incomplete else ""
    last_block = (
        f'<div class="prompt-row"><span class="lbl">last</span> {last}</div>'
        if last and last != first
        else ""
    )
    default_open = " open" if incomplete else ""
    tokens_sub = f'<span class="tokens">{fmt_tokens(s.billable_tokens)} tok</span>' if s.billable_tokens else ""
    icons = render_icon_row(s.cwd, Path(s.cwd).name)

    return f"""
    <article class="session {has_incomplete}" id="sid-{s.session_id}" data-sid="{s.session_id}" data-search="{html.escape(search_blob, quote=True)}">
      <details{default_open}>
        <summary>
          <div class="meta">
            <span class="time">{fmt_range(s.start_ts, s.end_ts)}</span>
            <span class="duration">{fmt_duration(s.start_ts, s.end_ts)}</span>
            <span class="msgs">{s.user_msg_count} msg{'s' if s.user_msg_count != 1 else ''}</span>
            {tokens_sub}
            {pill}
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <h3 style="flex: 1;">{title}</h3>
            {icons}
          </div>
          <div class="sid" title="click to copy" data-sid="{s.session_id}">{s.session_id}</div>
        </summary>
        <section class="prompts">
          <div class="prompt-row"><span class="lbl">first</span> {first}</div>
          {last_block}
        </section>
        <section>{tasks_html}</section>
        <form class="resume" action="/resume" method="post">
          <input type="hidden" name="sid" value="{s.session_id}">
          <input type="hidden" name="cwd" value="{html.escape(s.cwd)}">
          <input class="prompt-input" name="prompt" placeholder="Optional direction for resumed session…" autocomplete="off">
          <button type="submit">Resume ↻</button>
        </form>
      </details>
    </article>
    """


def _render_todo_row(t: dict, project_index: dict, known_sids: set, today: dt.date) -> tuple[str, str]:
    """Render one todo <li>. Returns (html, due_cls) so the caller can tally counts."""
    name = html.escape(t.get("name", "").strip() or "(untitled)")
    url = t.get("url", "")
    status = t.get("status", "")
    due = t.get("due")
    due_cls = ""
    due_label = ""
    if due:
        try:
            d = dt.date.fromisoformat(due[:10])
            if d < today:
                due_cls = "overdue"
            elif d == today:
                due_cls = "today"
            due_label = d.strftime("%b %d")
        except ValueError:
            due_label = due
    status_cls = "inprog" if status.lower() == "in progress" else "todo"
    due_html = f'<span class="todo-due">{html.escape(due_label)}</span>' if due_label else ""

    project_name = (t.get("project") or "").strip()
    match = project_index.get(project_name.lower()) if project_name else None
    prompt_val = html.escape(t.get("name") or "", quote=True)
    actions = []
    if match:
        cwd, latest_sid = match
        actions.append(
            f'<form class="todo-action" method="post" action="/start">'
            f'<input type="hidden" name="cwd" value="{html.escape(cwd)}">'
            f'<input type="hidden" name="prompt" value="{prompt_val}">'
            f'<button>▶ start in {html.escape(Path(cwd).name)}</button></form>'
        )
        if latest_sid:
            actions.append(
                f'<form class="todo-action" method="post" action="/resume">'
                f'<input type="hidden" name="sid" value="{latest_sid}">'
                f'<input type="hidden" name="cwd" value="{html.escape(cwd)}">'
                f'<input type="hidden" name="prompt" value="{prompt_val}">'
                f'<button>↻ resume latest</button></form>'
            )

    source_val = (t.get("source") or "").strip()
    if source_val and source_val in known_sids:
        source_html = (
            f'<a class="todo-source" href="#sid-{html.escape(source_val)}">'
            f'from {html.escape(source_val[:8])}</a>'
        )
    elif source_val:
        source_html = f'<span class="todo-source">via {html.escape(source_val)}</span>'
    else:
        source_html = ""

    notion_link = (
        f'<a class="todo-open" href="{html.escape(url)}" target="_blank">open in notion ↗</a>'
        if url else ""
    )

    body_bits = [source_html, "".join(actions), notion_link]
    body_html = "".join(b for b in body_bits if b)
    body_html = f'<div class="todo-body">{body_html}</div>' if body_html else ""

    row = (
        f'<li class="todo {due_cls}">'
        f'<details>'
        f'<summary>'
        f'<span class="todo-status {status_cls}"></span>'
        f'<span class="todo-name">{name}</span>'
        f'{due_html}'
        f'</summary>'
        f'{body_html}'
        f'</details>'
        f'</li>'
    )
    return row, due_cls


def render_notion_sidebar(todos: list[dict], source: str, fetched_at: str | None,
                          project_index: dict, known_sids: set) -> str:
    today = dt.date.today()
    overdue = 0
    today_count = 0

    groups: dict[str, list[dict]] = {}
    for t in todos:
        key = (t.get("project") or "").strip() or "Unassigned"
        groups.setdefault(key, []).append(t)

    group_blocks = []
    for project_name, items in sorted(
        groups.items(),
        key=lambda kv: (kv[0] == "Unassigned", -len(kv[1]), kv[0].lower()),
    ):
        rows = []
        for t in items:
            row, due_cls = _render_todo_row(t, project_index, known_sids, today)
            rows.append(row)
            if due_cls == "overdue":
                overdue += 1
            elif due_cls == "today":
                today_count += 1
        group_blocks.append(
            f'<details open class="todo-group">'
            f'<summary>'
            f'<span class="proj-name">{html.escape(project_name)}</span>'
            f'<span class="proj-count">{len(items)}</span>'
            f'</summary>'
            f'<ul class="todos">{"".join(rows)}</ul>'
            f'</details>'
        )

    if source == "live":
        src_note = '<span class="src ok">live</span>'
    elif source == "cache":
        ts_str = ""
        if fetched_at:
            try:
                t = dt.datetime.fromisoformat(fetched_at)
                ts_str = f" · {t.astimezone().strftime('%b %d %H:%M')}"
            except ValueError:
                pass
            ts_str = ts_str or f" · {fetched_at[:16]}"
        src_note = f'<span class="src stale">cached{ts_str}</span>'
    else:
        src_note = '<span class="src none">no token</span>'

    counts = []
    if overdue:
        counts.append(f'<span class="badge bad">{overdue} overdue</span>')
    if today_count:
        counts.append(f'<span class="badge warn">{today_count} due today</span>')
    counts.append(f'<span class="badge">{len(todos)} open</span>')

    body = "".join(group_blocks) or '<p class="muted">No open todos.</p>'
    config_hint = ""
    if source == "none":
        config_hint = (
            '<p class="hint">Add an internal-integration token:<br>'
            '<code>security add-generic-password -a notion -s todo-cli -w &lt;token&gt;</code></p>'
        )
    refresh_btn = '<form method="post" action="/refresh-notion" style="display:inline"><button class="mini" type="submit">refresh</button></form>'

    return f"""
    <aside class="sidebar">
      <div class="sidebar-head">
        <h2>Notion todos</h2>
        <div class="sidebar-meta">{src_note} {refresh_btn}</div>
      </div>
      <div class="counts">{''.join(counts)}</div>
      <div class="todo-groups">{body}</div>
      {config_hint}
    </aside>
    """


def _rate_block(label: str, rl: dict | None) -> str:
    if not rl:
        return ""
    pct = rl.get("used_percentage")
    resets = rl.get("resets_at") or rl.get("reset_at")
    if pct is None:
        return ""
    try:
        pct_f = float(pct)
    except (TypeError, ValueError):
        return ""
    cls = "good"
    if pct_f >= 90:
        cls = "bad"
    elif pct_f >= 70:
        cls = "warn"
    reset_str = ""
    if resets is not None:
        try:
            if isinstance(resets, (int, float)) or (isinstance(resets, str) and resets.isdigit()):
                r = dt.datetime.fromtimestamp(float(resets), tz=dt.timezone.utc)
            else:
                r = dt.datetime.fromisoformat(str(resets).replace("Z", "+00:00"))
            now = dt.datetime.now(dt.timezone.utc)
            secs = int((r - now).total_seconds())
            if secs > 0:
                if secs >= 86400:
                    reset_str = f"resets in {secs // 86400}d {(secs % 86400) // 3600}h"
                elif secs >= 3600:
                    reset_str = f"resets in {secs // 3600}h {(secs % 3600) // 60}m"
                else:
                    reset_str = f"resets in {secs // 60}m"
            else:
                reset_str = "reset due"
        except (ValueError, TypeError):
            reset_str = ""
    return f"""
      <div class="usage-block">
        <div class="lbl">{label}</div>
        <div class="val {cls}">{pct_f:.0f}%</div>
        <div class="sub">{reset_str}</div>
      </div>
    """


def render_usage_header(today_u: dict, week_u: dict, range_u: dict,
                        range_label: str, is_today_only: bool,
                        sub: dict | None) -> str:
    cache_pct = today_u["cache_hit_pct"]
    sub_blocks = ""
    if sub and sub.get("rate_limits"):
        rl = sub["rate_limits"]
        sub_blocks = (
            _rate_block("5h limit", rl.get("five_hour"))
            + _rate_block("7d limit", rl.get("seven_day"))
            + _rate_block("7d Opus", rl.get("seven_day_opus"))
            + _rate_block("7d Sonnet", rl.get("seven_day_sonnet"))
        )
    cost = ""
    if sub and isinstance(sub.get("cost"), dict):
        c = sub["cost"].get("total_cost_usd")
        if c is not None:
            try:
                cost = f"${float(c):.2f}"
            except (TypeError, ValueError):
                pass
    cost_sub = f" · {cost}" if cost else ""

    if is_today_only:
        first_block = f"""
      <div class="usage-block">
        <div class="lbl">Today</div>
        <div class="val">{fmt_tokens(today_u['billable'])}</div>
        <div class="sub">{today_u['session_count']} session{'s' if today_u['session_count'] != 1 else ''}{cost_sub}</div>
      </div>"""
    else:
        first_block = f"""
      <div class="usage-block">
        <div class="lbl">Range</div>
        <div class="val">{fmt_tokens(range_u['billable'])}</div>
        <div class="sub">{range_u['session_count']} session{'s' if range_u['session_count'] != 1 else ''} · {html.escape(range_label)}</div>
      </div>"""

    return f"""
    <div class="usage">{first_block}
      <div class="usage-block">
        <div class="lbl">Last 7d</div>
        <div class="val">{fmt_tokens(week_u['billable'])}</div>
        <div class="sub">{week_u['session_count']} session{'s' if week_u['session_count'] != 1 else ''}</div>
      </div>
      <div class="usage-block">
        <div class="lbl">Cache hit</div>
        <div class="val">{cache_pct:.0f}%</div>
        <div class="sub">{fmt_tokens(today_u['cache_read'])} cached today</div>
      </div>
      {sub_blocks}
    </div>
    """


def _home_collapse(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


def render_page(sessions, start_d, end_d, notion_todos, notion_source, notion_fetched_at,
                today_usage, week_usage, range_usage, project_index, known_sids):
    by_project = {}
    for s in sessions:
        by_project.setdefault(s.cwd, []).append(s)

    project_blocks = []
    total_open = 0
    for cwd, group in sorted(
        by_project.items(),
        key=lambda kv: -sum(1 for s in kv[1] if s.incomplete_tasks),
    ):
        open_in_group = sum(len(s.incomplete_tasks) for s in group)
        total_open += open_in_group
        group.sort(key=lambda s: (0 if s.incomplete_tasks else 1, -(s.end_ts.timestamp() if s.end_ts else 0)))
        cards = "".join(render_session_card(s) for s in group)
        plural = "s" if len(group) != 1 else ""
        base = Path(cwd).name or cwd
        open_note = f' · <span class="open">{open_in_group} open</span>' if open_in_group else ""
        icons = render_icon_row(cwd, base)
        project_blocks.append(
            f'<section class="project">'
            f'<h2 class="proj-head">'
            f'<span class="proj-base">{html.escape(base)}</span>'
            f'<span class="proj-path">{html.escape(_home_collapse(cwd))}</span>'
            f'<span class="proj-meta">{len(group)} session{plural}{open_note}</span>'
            f"{icons}"
            f"</h2>"
            f"{cards}</section>"
        )

    today = dt.date.today()
    is_today_only = start_d == today and end_d == today
    is_single_day = start_d == end_d
    span_days = (end_d - start_d).days + 1

    # Shift entire range by 1 day for prev/next arrows.
    prev_from = (start_d - dt.timedelta(days=1)).isoformat()
    prev_to = (end_d - dt.timedelta(days=1)).isoformat()
    next_from = (start_d + dt.timedelta(days=1)).isoformat()
    next_to = (end_d + dt.timedelta(days=1)).isoformat()

    # Quick-range URLs + active states.
    q_today = "/"
    q_7d = f"/?from={(today - dt.timedelta(days=6)).isoformat()}&to={today.isoformat()}"
    q_30d = f"/?from={(today - dt.timedelta(days=29)).isoformat()}&to={today.isoformat()}"
    cls_today = "active" if is_today_only else ""
    cls_7d = "active" if (start_d == today - dt.timedelta(days=6) and end_d == today) else ""
    cls_30d = "active" if (start_d == today - dt.timedelta(days=29) and end_d == today) else ""

    if is_single_day:
        if start_d == today:
            range_label = "today"
        else:
            range_label = start_d.isoformat()
    else:
        range_label = f"{start_d.isoformat()} → {end_d.isoformat()} ({span_days}d)"

    open_strong = (
        f' · <strong class="open-count">{total_open} open task{"s" if total_open != 1 else ""}</strong>'
        if total_open
        else ""
    )
    plural_s = "s" if len(sessions) != 1 else ""
    tokens_note = f' · {fmt_tokens(range_usage["billable"])} tokens' if range_usage["billable"] else ""
    body = "".join(project_blocks) or (
        '<div class="empty">'
        '<div class="empty-mark">∅</div>'
        '<p>No sessions in this range.</p>'
        f'<p class="muted">{html.escape(range_label)}</p>'
        '</div>'
    )

    sidebar = render_notion_sidebar(
        notion_todos, notion_source, notion_fetched_at, project_index, known_sids
    )
    sub = load_subscription_usage()
    usage = render_usage_header(today_usage, week_usage, range_usage, range_label, is_today_only, sub)

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>claude-dash · {html.escape(range_label)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css">
</head><body>
<header class="top">
  <div class="brand">
    <span class="brand-dot" aria-hidden="true"></span>
    <h1>claude<span class="brand-sep">·</span>dash</h1>
  </div>
  <nav class="range-picker" aria-label="date range">
    <a class="step" href="/?from={prev_from}&amp;to={prev_to}" title="shift 1 day earlier (←)">←</a>
    <form method="get" action="/" class="range-form">
      <input type="date" name="from" value="{start_d.isoformat()}" max="{end_d.isoformat()}" onchange="this.form.submit()" aria-label="from">
      <span class="sep">→</span>
      <input type="date" name="to" value="{end_d.isoformat()}" max="{today.isoformat()}" onchange="this.form.submit()" aria-label="to">
    </form>
    <a class="step" href="/?from={next_from}&amp;to={next_to}" title="shift 1 day later (→)">→</a>
    <div class="quick">
      <a class="{cls_today}" href="{q_today}">Today</a>
      <a class="{cls_7d}" href="{q_7d}">7d</a>
      <a class="{cls_30d}" href="{q_30d}">30d</a>
    </div>
  </nav>
  {usage}
</header>
<main>
  {sidebar}
  <section class="content">
    <div class="content-head">
      <p class="summary"><span class="count">{len(sessions)}</span> session{plural_s} · <span class="range">{html.escape(range_label)}</span>{open_strong}{tokens_note}</p>
      <input id="filter" class="filter" placeholder="Filter sessions…  /  to focus" autocomplete="off">
    </div>
    {body}
  </section>
</main>
<script>
  window.DASH_CONFIG = {{
    prevUrl: '/?from={prev_from}&to={prev_to}',
    nextUrl: '/?from={next_from}&to={next_to}'
  }};
</script>
<script src="/static/app.js"></script>
</body></html>
"""


def launch_start(cwd: str, prompt: str):
    if not Path(cwd).exists():
        return False, f"cwd does not exist: {cwd}"
    cmd = f"cd {shlex.quote(cwd)} && claude"
    if prompt.strip():
        cmd += f" {shlex.quote(prompt.strip())}"
    osascript = (
        'tell application "Terminal"\n'
        "  activate\n"
        f"  do script {json.dumps(cmd)}\n"
        "end tell"
    )
    try:
        subprocess.run(["osascript", "-e", osascript], check=True, capture_output=True)
        return True, cmd
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8", errors="replace")


def launch_resume(session_id: str, cwd: str, prompt: str):
    if not Path(cwd).exists():
        return False, f"cwd does not exist: {cwd}"
    parts = [f"cd {shlex.quote(cwd)}", f"claude --resume {shlex.quote(session_id)}"]
    if prompt.strip():
        parts[-1] += f" {shlex.quote(prompt.strip())}"
    cmd = " && ".join(parts)
    osascript = (
        'tell application "Terminal"\n'
        "  activate\n"
        f"  do script {json.dumps(cmd)}\n"
        "end tell"
    )
    try:
        subprocess.run(["osascript", "-e", osascript], check=True, capture_output=True)
        return True, cmd
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8", errors="replace")


def open_finder(cwd: str):
    try:
        subprocess.run(["open", cwd], check=True)
        return True, "ok"
    except Exception as e:
        return False, str(e)

def open_editor(cwd: str):
    # Try cursor first, then code
    for cmd in ["cursor", "code"]:
        try:
            subprocess.run([cmd, cwd], check=True)
            return True, f"opened with {cmd}"
        except FileNotFoundError:
            continue
        except Exception as e:
            return False, str(e)
    return False, "cursor/code not found in PATH"

def trigger_augment_index(cwd: str):
    # Run augment index in background
    def run():
        try:
            # Adjust path to auggie if needed
            subprocess.run(["/Users/nathan/.nvm/versions/node/v26.1.0/bin/auggie", "index", "--print"], cwd=cwd, check=True)
            # Update database indexed_at
            with database.get_db() as conn:
                conn.execute("INSERT OR REPLACE INTO project_meta(cwd, augment_indexed_at) VALUES (?, ?)",
                             (cwd, dt.datetime.now().isoformat()))
        except Exception as e:
            print(f"Augment index error: {e}")

    threading.Thread(target=run, daemon=True).start()
    return True, "indexing started"

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path.startswith("/static/"):
            file_path = Path(__file__).parent / parsed.path.lstrip("/")
            if file_path.exists():
                self.send_response(200)
                if file_path.suffix == ".css":
                    self.send_header("Content-Type", "text/css")
                elif file_path.suffix == ".js":
                    self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                self.wfile.write(file_path.read_bytes())
                return

        if parsed.path == "/search":
            q = params.get("q", [""])[0].strip()
            if not q:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps([]).encode())
                return

            results = database.search(q)
            out = []
            for r in results:
                out.append({
                    "session_id": r["session_id"],
                    "title": r["title"] or r["first_prompt"][:80] or r["session_id"],
                    "snippet": r["snippet"],
                    "cwd": r["cwd"],
                    "date": p.parse_ts(r["start_ts"]).strftime("%Y-%m-%d %H:%M") if r["start_ts"] else ""
                })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())
            return

        if parsed.path == "/open-finder":
            cwd = params.get("cwd", [""])[0]
            open_finder(cwd)
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/open-terminal":
            cwd = params.get("cwd", [""])[0]
            launch_start(cwd, "")
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/open-editor":
            cwd = params.get("cwd", [""])[0]
            open_editor(cwd)
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/augment/index":
            cwd = params.get("cwd", [""])[0]
            trigger_augment_index(cwd)
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/":
            qs = urllib.parse.parse_qs(parsed.query)
            today = dt.date.today()

            def parse_d(s):
                try:
                    return dt.date.fromisoformat(s) if s else None
                except ValueError:
                    return None

            date_p = (qs.get("date") or [None])[0]
            from_p = (qs.get("from") or [None])[0]
            to_p = (qs.get("to") or [None])[0]

            if date_p:
                d = parse_d(date_p) or today
                start_d, end_d = d, d
            else:
                start_d = parse_d(from_p)
                end_d = parse_d(to_p) or today  # default upper bound = today
                if start_d is None:
                    start_d = end_d  # default lower bound = end (single day)
                if start_d > end_d:
                    start_d, end_d = end_d, start_d

            week_start = today - dt.timedelta(days=6)
            week_sessions = load_sessions(since=week_start)
            today_sessions = [s for s in week_sessions if s.end_ts and s.end_ts.astimezone().date() == today]
            today_usage = usage_totals(today_sessions)
            week_usage = usage_totals(week_sessions)
            # Range sessions: reuse week data when possible, else fetch.
            if start_d >= week_start and end_d <= today:
                range_sessions = [
                    s for s in week_sessions
                    if s.end_ts and start_d <= s.end_ts.astimezone().date() <= end_d
                ]
            else:
                range_sessions = load_sessions(since=start_d, until=end_d)
            range_usage = usage_totals(range_sessions)
            todos, source, fetched_at = load_notion_todos()
            project_index = build_project_index(week_sessions)
            known_sids = {s.session_id for s in week_sessions}
            body = render_page(
                range_sessions, start_d, end_d, todos, source, fetched_at,
                today_usage, week_usage, range_usage, project_index, known_sids,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/refresh-notion":
            tok = notion_token()
            if tok:
                todos = fetch_notion_todos_live(tok)
                if todos is not None:
                    DASH_CACHE.mkdir(parents=True, exist_ok=True)
                    NOTION_CACHE_FILE.write_text(json.dumps({
                        "fetched_at": dt.datetime.now().astimezone().isoformat(),
                        "source": "api",
                        "db_id": NOTION_DB_ID,
                        "todos": todos,
                    }, indent=2))
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if parsed.path == "/start":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
            cwd = form.get("cwd", "").strip()
            prompt = form.get("prompt", "")
            if not cwd:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"missing cwd")
                return
            ok, info = launch_start(cwd, prompt)
            if ok:
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(info.encode("utf-8"))
            return
        if parsed.path != "/resume":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        sid = form.get("sid", "").strip()
        cwd = form.get("cwd", "").strip()
        prompt = form.get("prompt", "")
        if not sid or not cwd:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing sid or cwd")
            return
        ok, info = launch_resume(sid, cwd, prompt)
        if ok:
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(info.encode("utf-8"))


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--list":
        on_date = dt.date.today()
        if len(args) > 1:
            on_date = dt.date.fromisoformat(args[1])
        sessions = load_sessions(on_date)
        for s in sessions:
            print(f"{fmt_local(s.start_ts)}-{fmt_local(s.end_ts)}  {s.session_id}  {s.cwd}")
            print(f"  title: {s.title or s.first_prompt[:80]}")
            if s.tasks:
                for task in s.tasks.values():
                    mark = {"completed": "x", "in_progress": "~", "pending": " "}.get(task.status, "?")
                    print(f"  [{mark}] {task.subject}")
            print()
        return 0

    no_open = "--no-open" in args
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Claude dashboard on {url}", flush=True)
    if not no_open:
        try:
            subprocess.Popen(["open", url])
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        return 0


if __name__ == "__main__":
    sys.exit(main())
