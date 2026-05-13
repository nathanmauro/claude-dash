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


def load_sessions(on_date=None, since: dt.date | None = None):
    """If on_date set, return sessions ending on that day; if since set, sessions
    ending on/after that date; otherwise all sessions."""
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
            sessions.append(s)
    sessions.sort(
        key=lambda s: s.end_ts or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )
    return sessions


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
        todos.append({"name": name, "status": status, "due": due, "url": r.get("url")})
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


STATUS_BADGE = {
    "completed": ("done", "#1f7a3a"),
    "in_progress": ("in-progress", "#9a6b00"),
    "pending": ("pending", "#7a1f1f"),
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
        label, color = STATUS_BADGE.get(task.status, (task.status, "#555"))
        task_rows.append(
            f'<li><span class="status" style="background:{color}">{label}</span>'
            f'<span class="subject">{html.escape(task.subject)}</span></li>'
        )
    tasks_html = (
        f'<ul class="tasks">{"".join(task_rows)}</ul>'
        if task_rows
        else '<p class="muted">No tracked tasks.</p>'
    )

    first = (
        html.escape(truncate(s.first_prompt, 220))
        if s.first_prompt
        else '<span class="muted">(no user prompt)</span>'
    )
    last = html.escape(truncate(s.last_prompt, 220)) if s.last_prompt else ""

    title = html.escape(s.title or s.first_prompt[:80] or s.session_id)
    has_incomplete = "warn" if incomplete else ""
    last_block = (
        f'<div class="prompt-row"><span class="lbl">last:</span> {last}</div>'
        if last and last != first
        else ""
    )

    return f"""
    <article class="session {has_incomplete}" data-sid="{s.session_id}">
      <header>
        <div class="meta">
          <span class="time">{fmt_range(s.start_ts, s.end_ts)}</span>
          <span class="duration">({fmt_duration(s.start_ts, s.end_ts)})</span>
          {pill}
          <span class="msgs">{s.user_msg_count} msg{'s' if s.user_msg_count != 1 else ''}</span>
        </div>
        <h3>{title}</h3>
        <div class="sid">{s.session_id}</div>
      </header>
      <section class="prompts">
        <div class="prompt-row"><span class="lbl">first:</span> {first}</div>
        {last_block}
      </section>
      <section>{tasks_html}</section>
      <form class="resume" action="/resume" method="post">
        <input type="hidden" name="sid" value="{s.session_id}">
        <input type="hidden" name="cwd" value="{html.escape(s.cwd)}">
        <input class="prompt-input" name="prompt" placeholder="Optional direction prompt for resumed session…" autocomplete="off">
        <button type="submit">Resume</button>
      </form>
    </article>
    """


def render_notion_sidebar(todos: list[dict], source: str, fetched_at: str | None) -> str:
    today = dt.date.today()
    rows = []
    overdue = 0
    today_count = 0
    for t in todos:
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
                    overdue += 1
                elif d == today:
                    due_cls = "today"
                    today_count += 1
                due_label = d.strftime("%b %d")
            except ValueError:
                due_label = due
        status_cls = "inprog" if status.lower() == "in progress" else "todo"
        link_attr = f' href="{html.escape(url)}" target="_blank"' if url else ""
        due_html = f'<span class="todo-due">{due_label}</span>' if due_label else ""
        rows.append(
            f'<li class="todo {due_cls}"><a{link_attr}>'
            f'<span class="todo-status {status_cls}"></span>'
            f'<span class="todo-name">{name}</span>'
            f'{due_html}'
            f'</a></li>'
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

    body = "".join(rows) or '<li class="muted">No open todos.</li>'
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
      <ul class="todos">{body}</ul>
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


def render_usage_header(today_u: dict, week_u: dict, sub: dict | None) -> str:
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
    return f"""
    <div class="usage">
      <div class="usage-block">
        <div class="lbl">Today</div>
        <div class="val">{fmt_tokens(today_u['billable'])}</div>
        <div class="sub">{today_u['session_count']} session{'s' if today_u['session_count'] != 1 else ''}{cost_sub}</div>
      </div>
      <div class="usage-block">
        <div class="lbl">Last 7d</div>
        <div class="val">{fmt_tokens(week_u['billable'])}</div>
        <div class="sub">{week_u['session_count']} session{'s' if week_u['session_count'] != 1 else ''}</div>
      </div>
      <div class="usage-block">
        <div class="lbl">Cache hit</div>
        <div class="val">{cache_pct:.0f}%</div>
        <div class="sub">{fmt_tokens(today_u['cache_read'])} cached</div>
      </div>
      {sub_blocks}
    </div>
    """


def render_page(sessions, on_date, notion_todos, notion_source, notion_fetched_at,
                today_usage, week_usage):
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
        open_note = f", {open_in_group} open" if open_in_group else ""
        project_blocks.append(
            f'<section class="project">'
            f'<h2>{html.escape(cwd)} <small>{len(group)} session{plural}{open_note}</small></h2>'
            f"{cards}</section>"
        )

    today = dt.date.today()
    nav_prev = (on_date - dt.timedelta(days=1)).isoformat()
    nav_next = (on_date + dt.timedelta(days=1)).isoformat()
    today_link = '<a href="/">today</a>' if on_date != today else ""
    open_strong = (
        f' · <strong>{total_open} open task{"s" if total_open != 1 else ""}</strong>'
        if total_open
        else ""
    )
    plural_s = "s" if len(sessions) != 1 else ""
    body = "".join(project_blocks) or '<p class="muted">No sessions found for this date.</p>'

    sidebar = render_notion_sidebar(notion_todos, notion_source, notion_fetched_at)
    sub = load_subscription_usage()
    usage = render_usage_header(today_usage, week_usage, sub)

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Claude dashboard — {on_date.isoformat()}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font: 14px/1.45 -apple-system, BlinkMacSystemFont, system-ui, sans-serif; margin: 0; padding: 0; color: #1c1c1e; background: #f5f5f7; }}
  header.top {{ background: #fff; border-bottom: 1px solid #e0e0e0; padding: 14px 24px; display: flex; gap: 24px; align-items: center; flex-wrap: wrap; position: sticky; top: 0; z-index: 10; }}
  header.top h1 {{ font-size: 18px; margin: 0; }}
  .usage {{ display: flex; gap: 18px; margin-left: auto; }}
  .usage-block {{ text-align: center; min-width: 90px; }}
  .usage-block .lbl {{ font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
  .usage-block .val {{ font-size: 20px; font-weight: 600; color: #1c1c1e; line-height: 1.1; }}
  .usage-block .val.warn {{ color: #92400e; }}
  .usage-block .val.bad {{ color: #991b1b; }}
  .usage-block .val.good {{ color: #166534; }}
  .usage-block .sub {{ font-size: 11px; color: #888; }}
  nav {{ display: flex; gap: 8px; align-items: center; }}
  nav a, nav input {{ font: inherit; }}
  nav a {{ color: #0a64c4; text-decoration: none; padding: 4px 10px; border-radius: 6px; background: #fff; border: 1px solid #ddd; font-size: 13px; }}
  nav input[type=date] {{ padding: 4px 6px; border: 1px solid #ccc; border-radius: 6px; }}
  main {{ display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 0; }}
  aside.sidebar {{ background: #fafafa; border-right: 1px solid #e0e0e0; padding: 16px 14px; min-height: calc(100vh - 60px); }}
  .sidebar-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
  .sidebar-head h2 {{ font-size: 14px; margin: 0; color: #444; }}
  .sidebar-meta .src {{ font-size: 10px; padding: 1px 6px; border-radius: 8px; margin-right: 4px; }}
  .src.ok {{ background: #dcfce7; color: #166534; }}
  .src.stale {{ background: #fef3c7; color: #92400e; }}
  .src.none {{ background: #fee2e2; color: #991b1b; }}
  button.mini {{ font-size: 10px; padding: 1px 6px; background: #fff; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; color: #444; }}
  button.mini:hover {{ background: #eee; }}
  .counts {{ display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }}
  .badge {{ font-size: 10px; padding: 2px 7px; border-radius: 8px; background: #e5e5e5; color: #444; }}
  .badge.warn {{ background: #fef3c7; color: #92400e; }}
  .badge.bad {{ background: #fee2e2; color: #991b1b; }}
  ul.todos {{ list-style: none; padding: 0; margin: 0; }}
  ul.todos li.todo a {{ display: flex; gap: 6px; align-items: center; padding: 5px 6px; text-decoration: none; color: #1c1c1e; border-radius: 4px; font-size: 12px; line-height: 1.3; }}
  ul.todos li.todo a:hover {{ background: #e9e9e9; }}
  .todo-status {{ width: 8px; height: 8px; border-radius: 50%; background: #999; flex-shrink: 0; }}
  .todo-status.inprog {{ background: #0a64c4; }}
  .todo-name {{ flex: 1; min-width: 0; }}
  .todo-due {{ font-size: 10px; color: #888; white-space: nowrap; }}
  .todo.overdue .todo-name {{ color: #991b1b; font-weight: 600; }}
  .todo.overdue .todo-due {{ color: #991b1b; }}
  .todo.today .todo-due {{ color: #92400e; font-weight: 600; }}
  .hint {{ font-size: 11px; color: #666; margin-top: 12px; }}
  .hint code {{ display: block; background: #1c1c1e; color: #f5f5f7; padding: 6px 8px; border-radius: 4px; font-size: 10px; margin-top: 4px; word-break: break-all; }}
  section.content {{ padding: 20px 24px; max-width: 1000px; }}
  h2 {{ font-size: 15px; margin: 28px 0 10px; color: #444; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  h2:first-child {{ margin-top: 0; }}
  h2 small {{ color: #999; font-weight: 400; margin-left: 8px; }}
  h3 {{ font-size: 15px; margin: 2px 0 4px; font-weight: 600; }}
  .summary {{ color: #555; margin-bottom: 6px; }}
  .session {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px 14px; margin: 8px 0; }}
  .session.warn {{ border-left: 4px solid #d97706; }}
  .session header {{ display: flex; flex-direction: column; }}
  .meta {{ font-size: 12px; color: #777; display: flex; gap: 8px; align-items: center; }}
  .sid {{ font: 11px ui-monospace, Menlo, monospace; color: #aaa; margin-top: 2px; }}
  .pill {{ font-size: 11px; padding: 1px 8px; border-radius: 10px; }}
  .pill.warn {{ background: #fef3c7; color: #92400e; }}
  .pill.ok {{ background: #dcfce7; color: #166534; }}
  .prompts {{ margin: 8px 0; font-size: 13px; color: #333; }}
  .prompt-row {{ margin: 2px 0; }}
  .prompt-row .lbl {{ color: #888; font-size: 11px; margin-right: 4px; text-transform: uppercase; }}
  .tasks {{ list-style: none; padding: 0; margin: 6px 0; }}
  .tasks li {{ display: flex; align-items: flex-start; gap: 8px; padding: 3px 0; }}
  .tasks .status {{ display: inline-block; min-width: 90px; text-align: center; font-size: 10px; padding: 2px 6px; border-radius: 3px; color: white; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
  .tasks .subject {{ flex: 1; }}
  form.resume {{ display: flex; gap: 6px; margin-top: 10px; }}
  form.resume input.prompt-input {{ flex: 1; padding: 6px 10px; border: 1px solid #ccc; border-radius: 6px; font: inherit; }}
  form.resume button {{ padding: 6px 14px; background: #0a64c4; color: white; border: 0; border-radius: 6px; cursor: pointer; font: inherit; }}
  form.resume button:hover {{ background: #084e9b; }}
  .muted {{ color: #999; font-style: italic; padding: 6px; }}
  .project {{ margin-bottom: 12px; }}
</style>
</head><body>
<header class="top">
  <h1>Claude dashboard</h1>
  <nav>
    <a href="/?date={nav_prev}">←</a>
    <form style="display:inline" method="get" action="/">
      <input type="date" name="date" value="{on_date.isoformat()}" onchange="this.form.submit()">
    </form>
    <a href="/?date={nav_next}">→</a>
    {today_link}
  </nav>
  {usage}
</header>
<main>
  {sidebar}
  <section class="content">
    <p class="summary">{len(sessions)} session{plural_s} on {on_date.isoformat()}{open_strong}.</p>
    {body}
  </section>
</main>
</body></html>
"""


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
            date_str = (qs.get("date") or [dt.date.today().isoformat()])[0]
            try:
                on_date = dt.date.fromisoformat(date_str)
            except ValueError:
                on_date = dt.date.today()
            week_start = dt.date.today() - dt.timedelta(days=6)
            week_sessions = load_sessions(since=week_start)
            day_sessions = [s for s in week_sessions if s.end_ts and s.end_ts.astimezone().date() == on_date]
            # Sessions for other days (older than week) — only fetch if needed
            if on_date < week_start:
                day_sessions = load_sessions(on_date=on_date)
            today_sessions = [s for s in week_sessions if s.end_ts and s.end_ts.astimezone().date() == dt.date.today()]
            today_usage = usage_totals(today_sessions)
            week_usage = usage_totals(week_sessions)
            todos, source, fetched_at = load_notion_todos()
            body = render_page(
                day_sessions, on_date, todos, source, fetched_at, today_usage, week_usage
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
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        on_date = dt.date.today()
        if len(sys.argv) > 2:
            on_date = dt.date.fromisoformat(sys.argv[2])
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

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Claude dashboard on {url}")
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
