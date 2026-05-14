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
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
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
KEYCHAIN_SERVICE = "todo-cli"


@dataclass
class Task:
    task_id: str
    subject: str
    description: str
    status: str = "pending"  # pending | in_progress | completed


@dataclass
class Session:
    session_id: str
    project_dir: str
    cwd: str
    path: Path
    start_ts: dt.datetime | None = None
    end_ts: dt.datetime | None = None
    title: str = ""
    first_prompt: str = ""
    last_prompt: str = ""
    user_prompts: list[str] = field(default_factory=list)
    tasks: dict[str, Task] = field(default_factory=dict)
    user_msg_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_create_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def billable_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_create_tokens

    @property
    def total_tokens(self) -> int:
        return self.billable_tokens + self.cache_read_tokens

    @property
    def incomplete_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status != "completed"]

    @property
    def completed_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status == "completed"]


def decode_project_dir(name: str) -> str:
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name.replace("-", "/")


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(c.get("text", ""))
        return "\n".join(out)
    return ""


def is_real_user_prompt(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    if t.startswith("<command-") or t.startswith("<local-command-"):
        return False
    if t.startswith("<system-reminder"):
        return False
    if "Caveat: The messages below were generated" in t:
        return False
    return True


def parse_session(path: Path):
    project_dir = path.parent.name
    sess = Session(
        session_id=path.stem,
        project_dir=project_dir,
        cwd=decode_project_dir(project_dir),
        path=path,
    )
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = j.get("type")
                if j.get("cwd"):
                    sess.cwd = j["cwd"]
                ts = parse_ts(j.get("timestamp"))
                if ts:
                    if sess.start_ts is None or ts < sess.start_ts:
                        sess.start_ts = ts
                    if sess.end_ts is None or ts > sess.end_ts:
                        sess.end_ts = ts
                if t == "ai-title":
                    sess.title = j.get("aiTitle", "") or sess.title
                elif t == "user" and not j.get("isSidechain") and not j.get("isMeta"):
                    msg = j.get("message", {}) or {}
                    text = extract_text(msg.get("content", ""))
                    if is_real_user_prompt(text):
                        sess.user_msg_count += 1
                        snippet = text.strip()
                        if not sess.first_prompt:
                            sess.first_prompt = snippet
                        sess.last_prompt = snippet
                        if len(sess.user_prompts) < 50:
                            sess.user_prompts.append(snippet)
                elif t == "assistant" and not j.get("isSidechain"):
                    msg = j.get("message", {}) or {}
                    usage = msg.get("usage") or {}
                    sess.input_tokens += usage.get("input_tokens", 0) or 0
                    sess.output_tokens += usage.get("output_tokens", 0) or 0
                    sess.cache_create_tokens += usage.get("cache_creation_input_tokens", 0) or 0
                    sess.cache_read_tokens += usage.get("cache_read_input_tokens", 0) or 0
                    for c in msg.get("content", []):
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") != "tool_use":
                            continue
                        name = c.get("name")
                        inp = c.get("input", {}) or {}
                        if name == "TaskCreate":
                            tid = str(inp.get("taskId") or len(sess.tasks) + 1)
                            sess.tasks[tid] = Task(
                                task_id=tid,
                                subject=inp.get("subject", ""),
                                description=inp.get("description", ""),
                            )
                        elif name == "TaskUpdate":
                            tid = str(inp.get("taskId", ""))
                            if tid in sess.tasks:
                                status = inp.get("status")
                                if status:
                                    sess.tasks[tid].status = status
    except OSError:
        return None
    if sess.start_ts is None:
        return None
    return sess


def load_sessions(on_date=None, since: dt.date | None = None, until: dt.date | None = None):
    """Filter sessions by local ending date.
    - on_date: exact day match
    - since + until: inclusive range
    - since only: from that date onwards
    - until only: up to that date
    Otherwise return all sessions."""
    sessions = []
    if not PROJECTS_DIR.exists():
        return sessions
    for proj in PROJECTS_DIR.iterdir():
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            s = parse_session(jsonl)
            if not s:
                continue
            local_end = s.end_ts.astimezone().date() if s.end_ts else None
            if on_date and local_end != on_date:
                continue
            if since and (not local_end or local_end < since):
                continue
            if until and (not local_end or local_end > until):
                continue
            sessions.append(s)
    sessions.sort(
        key=lambda s: s.end_ts or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )
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
          <h3>{title}</h3>
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
        project_blocks.append(
            f'<section class="project">'
            f'<h2 class="proj-head">'
            f'<span class="proj-base">{html.escape(base)}</span>'
            f'<span class="proj-path">{html.escape(_home_collapse(cwd))}</span>'
            f'<span class="proj-meta">{len(group)} session{plural}{open_note}</span>'
            f'</h2>'
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
<style>
  :root {{
    --bg: #0c0d0f;
    --surface: #131418;
    --surface-2: #1a1c21;
    --surface-3: #22242a;
    --line: #26282d;
    --line-2: #34373c;
    --line-3: #44474d;
    --text: #e6e7ea;
    --dim: #8a8d94;
    --muted: #54575e;
    --accent: #cc785c;
    --accent-hi: #e08c70;
    --accent-tint: rgba(204,120,92,0.13);
    --good: #86c39b;
    --good-tint: rgba(134,195,155,0.12);
    --warn: #e3b56b;
    --warn-tint: rgba(227,181,107,0.13);
    --bad: #e08a82;
    --bad-tint: rgba(224,138,130,0.12);
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ background: var(--bg); }}
  body {{
    margin: 0;
    color: var(--text);
    font: 14px/1.55 "IBM Plex Sans", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
    letter-spacing: 0.005em;
  }}
  body::before {{
    content: "";
    position: fixed; inset: 0;
    pointer-events: none; z-index: 1;
    background:
      radial-gradient(1200px 600px at 80% -10%, rgba(204,120,92,0.04), transparent 60%),
      radial-gradient(900px 500px at -10% 50%, rgba(134,195,155,0.025), transparent 60%);
  }}

  /* Header bar */
  header.top {{
    position: sticky; top: 0; z-index: 100;
    background: rgba(12,13,15,0.86);
    backdrop-filter: blur(12px) saturate(140%);
    -webkit-backdrop-filter: blur(12px) saturate(140%);
    border-bottom: 1px solid var(--line);
    padding: 12px 24px;
    display: flex; align-items: center;
    gap: 18px; flex-wrap: wrap;
  }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .brand-dot {{
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 10px var(--accent);
    animation: pulse 2.8s ease-in-out infinite;
  }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.45; }} }}
  header.top h1 {{
    font: 600 13px/1 "JetBrains Mono", monospace;
    margin: 0; color: var(--text);
    letter-spacing: 0.1em; text-transform: uppercase;
  }}
  .brand-sep {{ color: var(--accent); margin: 0 1px; }}

  /* Range picker */
  .range-picker {{
    display: flex; align-items: center; gap: 6px;
    font-family: "JetBrains Mono", monospace; font-size: 12px;
  }}
  .range-picker .step {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 30px;
    color: var(--dim);
    text-decoration: none;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--surface);
    transition: 80ms;
  }}
  .range-picker .step:hover {{ color: var(--accent); border-color: var(--line-2); }}
  .range-form {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 0 6px;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--surface);
    height: 30px;
  }}
  .range-form input[type=date] {{
    background: transparent; border: 0;
    color: var(--text); font: inherit;
    padding: 5px 4px;
    color-scheme: dark;
    cursor: pointer; outline: none;
  }}
  .range-form input[type=date]:focus {{ color: var(--accent); }}
  .range-form .sep {{ color: var(--muted); font-size: 11px; padding: 0 2px; }}
  .range-picker .quick {{
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--surface);
    overflow: hidden;
    margin-left: 2px;
    height: 30px;
  }}
  .range-picker .quick a {{
    padding: 7px 12px;
    color: var(--dim);
    text-decoration: none;
    font-size: 11px;
    border-right: 1px solid var(--line);
    transition: 80ms;
    display: inline-flex; align-items: center;
  }}
  .range-picker .quick a:last-child {{ border-right: 0; }}
  .range-picker .quick a:hover {{ color: var(--text); background: var(--surface-2); }}
  .range-picker .quick a.active {{ color: var(--accent); background: var(--surface-2); }}

  /* Usage strip */
  .usage {{
    display: flex; margin-left: auto;
    border-left: 1px solid var(--line);
    font-family: "JetBrains Mono", monospace;
  }}
  .usage-block {{
    padding: 0 16px;
    border-right: 1px solid var(--line);
    min-width: 92px;
    text-align: left;
  }}
  .usage-block:last-child {{ border-right: 0; }}
  .usage-block .lbl {{
    font-size: 9px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.14em;
    margin-bottom: 4px;
  }}
  .usage-block .val {{
    font-size: 18px; font-weight: 600; line-height: 1;
    color: var(--text);
    font-feature-settings: "tnum","ss01";
  }}
  .usage-block .val.good {{ color: var(--good); }}
  .usage-block .val.warn {{ color: var(--warn); }}
  .usage-block .val.bad {{ color: var(--bad); }}
  .usage-block .sub {{ font-size: 10px; color: var(--dim); margin-top: 4px; }}

  /* Layout */
  main {{
    display: grid;
    grid-template-columns: 320px minmax(0, 1fr);
    position: relative; z-index: 2;
  }}
  aside.sidebar {{
    background: var(--surface);
    border-right: 1px solid var(--line);
    padding: 18px 16px;
    position: sticky; top: 65px;
    align-self: start;
    max-height: calc(100vh - 65px);
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--line-2) transparent;
  }}
  aside.sidebar::-webkit-scrollbar {{ width: 6px; }}
  aside.sidebar::-webkit-scrollbar-thumb {{ background: var(--line-2); border-radius: 3px; }}

  .sidebar-head {{
    display: flex; justify-content: space-between; align-items: baseline;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 12px;
  }}
  .sidebar-head h2 {{
    font: 600 10px/1 "JetBrains Mono", monospace;
    color: var(--dim); margin: 0;
    text-transform: uppercase; letter-spacing: 0.16em;
  }}
  .sidebar-meta {{ display: flex; align-items: center; gap: 6px; }}
  .sidebar-meta .src {{
    font: 600 9px/1 "JetBrains Mono", monospace;
    padding: 3px 7px; border-radius: 3px;
    text-transform: uppercase; letter-spacing: 0.06em;
  }}
  .src.ok {{ background: var(--good-tint); color: var(--good); }}
  .src.stale {{ background: var(--warn-tint); color: var(--warn); }}
  .src.none {{ background: var(--bad-tint); color: var(--bad); }}
  button.mini {{
    font: 9px/1 "JetBrains Mono", monospace;
    text-transform: uppercase; letter-spacing: 0.06em;
    padding: 4px 7px;
    background: var(--surface-2); border: 1px solid var(--line);
    border-radius: 3px; color: var(--dim); cursor: pointer;
    transition: 80ms;
  }}
  button.mini:hover {{ color: var(--accent); border-color: var(--line-2); }}
  .counts {{ display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }}
  .badge {{
    font: 9px/1 "JetBrains Mono", monospace;
    padding: 3px 7px; border-radius: 3px;
    background: var(--surface-3); color: var(--dim);
    text-transform: uppercase; letter-spacing: 0.06em;
  }}
  .badge.warn {{ background: var(--warn-tint); color: var(--warn); }}
  .badge.bad {{ background: var(--bad-tint); color: var(--bad); }}

  /* Todo groups */
  .todo-groups {{ display: flex; flex-direction: column; gap: 2px; }}
  details.todo-group {{ margin: 0; }}
  details.todo-group > summary {{
    cursor: pointer;
    padding: 7px 4px 5px;
    font: 500 11px/1 "JetBrains Mono", monospace;
    color: var(--text);
    text-transform: uppercase; letter-spacing: 0.08em;
    list-style: none;
    display: flex; align-items: baseline; gap: 6px;
    border-radius: 3px;
  }}
  details.todo-group > summary::-webkit-details-marker {{ display: none; }}
  details.todo-group > summary::before {{
    content: "▸"; color: var(--muted); font-size: 8px;
  }}
  details.todo-group[open] > summary::before {{ content: "▾"; }}
  details.todo-group > summary:hover {{ background: var(--surface-2); }}
  .proj-name {{
    flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .proj-count {{ color: var(--muted); font-weight: 400; font-size: 10px; }}

  ul.todos {{ list-style: none; padding: 0; margin: 0 0 4px; }}
  .todo details > summary {{
    cursor: pointer;
    display: flex; gap: 8px; align-items: center;
    padding: 5px 6px;
    list-style: none;
    font-size: 12px;
    border-radius: 3px;
  }}
  .todo details > summary::-webkit-details-marker {{ display: none; }}
  .todo details > summary:hover {{ background: var(--surface-2); }}
  .todo-status {{
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--muted); flex-shrink: 0;
  }}
  .todo-status.inprog {{ background: var(--accent); box-shadow: 0 0 6px var(--accent); }}
  .todo-name {{
    flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .todo-due {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; color: var(--dim); white-space: nowrap;
  }}
  .todo.overdue .todo-name {{ color: var(--bad); font-weight: 500; }}
  .todo.overdue .todo-due {{ color: var(--bad); }}
  .todo.today .todo-due {{ color: var(--warn); font-weight: 600; }}

  .todo-body {{
    padding: 4px 8px 8px 22px;
    display: flex; flex-direction: column; gap: 4px;
  }}
  .todo-body form.todo-action {{ display: inline; margin: 0; }}
  .todo-body form.todo-action button {{
    font: 10px/1 "JetBrains Mono", monospace;
    padding: 4px 8px;
    border: 1px solid var(--line);
    background: var(--surface-2);
    border-radius: 3px;
    cursor: pointer; color: var(--dim);
    letter-spacing: 0.04em;
    transition: 80ms;
  }}
  .todo-body form.todo-action button:hover {{
    color: var(--accent); border-color: var(--line-2);
  }}
  .todo-source {{ font-size: 11px; color: var(--muted); }}
  a.todo-source {{ color: var(--dim); text-decoration: none; border-bottom: 1px dashed var(--line-2); }}
  a.todo-source:hover {{ color: var(--accent); border-color: var(--accent); }}
  .todo-open {{ font-size: 11px; color: var(--dim); text-decoration: none; }}
  .todo-open:hover {{ color: var(--accent); }}

  .hint {{ font-size: 11px; color: var(--muted); margin-top: 14px; line-height: 1.5; }}
  .hint code {{
    display: block;
    background: var(--surface-3); color: var(--text);
    padding: 8px 10px; border-radius: 4px;
    font: 10px/1.5 "JetBrains Mono", monospace;
    margin-top: 6px; word-break: break-all;
    border: 1px solid var(--line);
  }}

  /* Content area */
  section.content {{ padding: 22px 28px 60px; max-width: 1100px; }}
  .content-head {{
    display: flex; align-items: center; gap: 14px;
    margin-bottom: 22px; padding-bottom: 12px;
    border-bottom: 1px dashed var(--line);
  }}
  .summary {{
    margin: 0; color: var(--dim); font-size: 13px; flex: 1;
  }}
  .summary .count {{
    font-family: "JetBrains Mono", monospace;
    color: var(--text); font-weight: 600;
  }}
  .summary .range {{
    font-family: "JetBrains Mono", monospace;
    color: var(--accent);
  }}
  .summary .open-count {{
    color: var(--warn);
    font-family: "JetBrains Mono", monospace;
    font-weight: 500;
  }}
  .filter {{
    background: var(--surface);
    border: 1px solid var(--line);
    color: var(--text);
    padding: 7px 10px;
    border-radius: 4px;
    font: 12px "IBM Plex Sans", sans-serif;
    width: 220px;
    outline: none; transition: 120ms;
  }}
  .filter:focus {{ border-color: var(--accent); width: 280px; }}
  .filter::placeholder {{ color: var(--muted); }}

  /* Project section */
  .project {{ margin-bottom: 32px; }}
  .proj-head {{
    display: flex; align-items: baseline; gap: 12px;
    margin: 0 0 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--line);
    font: 500 15px "IBM Plex Sans", sans-serif;
  }}
  .proj-base {{ color: var(--text); font-weight: 600; }}
  .proj-path {{
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; color: var(--muted);
    letter-spacing: 0.02em;
  }}
  .proj-meta {{
    margin-left: auto;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--dim);
  }}
  .proj-meta .open {{ color: var(--warn); }}

  /* Session card */
  .session {{
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 5px;
    margin: 8px 0;
    transition: border-color 120ms, transform 80ms;
  }}
  .session:hover {{ border-color: var(--line-2); }}
  .session.warn {{ border-left: 2px solid var(--accent); }}
  .session details > summary {{
    cursor: pointer;
    list-style: none;
    padding: 14px 16px;
    position: relative;
  }}
  .session details > summary::-webkit-details-marker {{ display: none; }}
  .session details > summary::after {{
    content: "▾";
    position: absolute; right: 16px; top: 16px;
    color: var(--muted); font-size: 10px;
    transition: 80ms;
  }}
  .session details:not([open]) > summary::after {{ content: "▸"; }}
  .session details > summary:hover h3 {{ color: var(--accent); }}

  .session .meta {{
    display: flex; gap: 10px; align-items: center;
    font: 10px/1 "JetBrains Mono", monospace;
    color: var(--dim);
    margin-bottom: 6px;
    flex-wrap: wrap;
    text-transform: uppercase; letter-spacing: 0.06em;
  }}
  .session .meta .time {{ color: var(--text); }}
  .session .meta .duration {{ color: var(--muted); }}
  .session h3 {{
    font: 500 14px/1.4 "IBM Plex Sans", sans-serif;
    margin: 0 30px 4px 0;
    color: var(--text);
    transition: color 80ms;
  }}
  .session .sid {{
    font: 10px/1 "JetBrains Mono", monospace;
    color: var(--muted);
    letter-spacing: 0.04em;
    cursor: pointer;
    display: inline-block;
    padding: 2px 0;
  }}
  .session .sid:hover {{ color: var(--dim); }}
  .session .sid.copied {{ color: var(--good); }}
  .session .sid.copied::after {{ content: " ✓ copied"; }}

  .pill {{
    font: 9px/1 "JetBrains Mono", monospace;
    padding: 3px 7px; border-radius: 3px;
    text-transform: uppercase; letter-spacing: 0.06em;
    border: 1px solid transparent;
  }}
  .pill.warn {{ background: var(--warn-tint); color: var(--warn); border-color: rgba(227,181,107,0.25); }}
  .pill.ok {{ background: var(--good-tint); color: var(--good); border-color: rgba(134,195,155,0.25); }}

  .session details[open] > summary {{ border-bottom: 1px solid var(--line); }}
  .session details > section,
  .session details > form {{ padding: 0 16px; }}
  .session details > section:first-of-type {{ padding-top: 12px; }}

  .prompts {{
    font-size: 13px; color: var(--text);
    padding-top: 12px; padding-bottom: 4px;
  }}
  .prompt-row {{
    margin: 4px 0;
    display: flex; align-items: baseline; gap: 10px;
  }}
  .prompt-row .lbl {{
    font: 9px/1 "JetBrains Mono", monospace;
    color: var(--muted);
    letter-spacing: 0.12em; text-transform: uppercase;
    flex-shrink: 0; width: 32px;
  }}

  .tasks {{ list-style: none; padding: 0; margin: 4px 0 8px; }}
  .tasks li {{
    display: flex; align-items: flex-start; gap: 10px;
    padding: 6px 0;
    border-top: 1px dashed var(--line);
    font-size: 13px;
  }}
  .tasks li:first-child {{ border-top: 0; }}
  .tasks .status {{
    display: inline-block;
    min-width: 60px; text-align: center;
    padding: 2px 6px;
    font: 9px/1.5 "JetBrains Mono", monospace;
    letter-spacing: 0.08em; text-transform: uppercase;
    border-radius: 2px;
    flex-shrink: 0;
  }}
  .tasks .status.completed {{ background: var(--good-tint); color: var(--good); }}
  .tasks .status.in_progress {{ background: var(--warn-tint); color: var(--warn); }}
  .tasks .status.pending {{ background: var(--bad-tint); color: var(--bad); }}
  .tasks .subject {{ flex: 1; color: var(--text); }}

  form.resume {{
    display: flex; gap: 8px;
    margin-top: 14px;
    padding-top: 12px; padding-bottom: 14px;
    border-top: 1px dashed var(--line);
  }}
  form.resume input.prompt-input {{
    flex: 1;
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 7px 10px;
    font: 13px "IBM Plex Sans", sans-serif;
    outline: none; transition: 80ms;
  }}
  form.resume input.prompt-input:focus {{ border-color: var(--accent); }}
  form.resume input.prompt-input::placeholder {{ color: var(--muted); }}
  form.resume button {{
    background: var(--accent);
    color: #0c0d0f;
    border: 0;
    border-radius: 4px;
    padding: 7px 16px;
    font: 600 11px "JetBrains Mono", monospace;
    text-transform: uppercase; letter-spacing: 0.08em;
    cursor: pointer; transition: 80ms;
  }}
  form.resume button:hover {{ background: var(--accent-hi); }}

  .muted {{
    color: var(--muted); font-style: italic;
    padding: 8px 0; font-size: 13px;
  }}

  .empty {{
    text-align: center; padding: 80px 0;
    color: var(--dim);
  }}
  .empty-mark {{
    font: 500 72px/1 "JetBrains Mono", monospace;
    color: var(--line-2);
    margin-bottom: 16px;
  }}
  .empty p {{ margin: 4px 0; }}

  /* Keyboard hint pill */
  .kbd {{
    font: 9px/1 "JetBrains Mono", monospace;
    padding: 2px 5px;
    border: 1px solid var(--line-2);
    border-radius: 3px;
    color: var(--dim);
    background: var(--surface);
    margin: 0 2px;
  }}

  @media (max-width: 880px) {{
    main {{ grid-template-columns: 1fr; }}
    aside.sidebar {{
      position: static;
      max-height: none;
      border-right: 0;
      border-bottom: 1px solid var(--line);
    }}
    .usage {{ margin-left: 0; border-left: 0; }}
  }}
</style>
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
(() => {{
  const PREV = '/?from={prev_from}&to={prev_to}';
  const NEXT = '/?from={next_from}&to={next_to}';
  const filter = document.getElementById('filter');

  // Click-to-copy session id
  document.querySelectorAll('.sid[data-sid]').forEach(el => {{
    el.addEventListener('click', e => {{
      e.preventDefault();
      e.stopPropagation();
      const sid = el.dataset.sid;
      if (navigator.clipboard) {{
        navigator.clipboard.writeText(sid).then(() => {{
          el.classList.add('copied');
          setTimeout(() => el.classList.remove('copied'), 1000);
        }});
      }}
    }});
  }});

  // Client-side filter
  if (filter) {{
    const apply = () => {{
      const q = filter.value.trim().toLowerCase();
      document.querySelectorAll('.session').forEach(card => {{
        const blob = card.dataset.search || '';
        card.style.display = (!q || blob.includes(q)) ? '' : 'none';
      }});
      document.querySelectorAll('.project').forEach(p => {{
        const any = [...p.querySelectorAll('.session')].some(c => c.style.display !== 'none');
        p.style.display = any ? '' : 'none';
      }});
    }};
    filter.addEventListener('input', apply);
  }}

  // Keyboard nav
  document.addEventListener('keydown', e => {{
    if (e.target.matches('input, textarea')) {{
      if (e.key === 'Escape' && e.target === filter) {{
        filter.value = '';
        filter.dispatchEvent(new Event('input'));
        filter.blur();
      }}
      return;
    }}
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowLeft') {{ location.href = PREV; }}
    else if (e.key === 'ArrowRight') {{ location.href = NEXT; }}
    else if (e.key === 't') {{ location.href = '/'; }}
    else if (e.key === '/') {{
      e.preventDefault();
      filter && filter.focus();
    }}
  }});
}})();
</script>
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
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
