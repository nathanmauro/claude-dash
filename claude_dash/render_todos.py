from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .models import NotionTodo


def build_project_index(sessions) -> dict[str, tuple[str, str]]:
    idx: dict[str, tuple[str, str]] = {}
    for s in sessions:
        cwd = s.cwd
        base = Path(cwd).name
        for key in (cwd.lower(), base.lower()):
            if key and key not in idx:
                idx[key] = (cwd, s.session_id)
    return idx


def _render_todo_row(
    t: NotionTodo, project_index: dict, known_sids: set, today: dt.date
) -> tuple[str, str]:
    name = html.escape(t.name.strip() or "(untitled)")
    url = t.url or ""
    status = t.status or ""
    due = t.due
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

    project_name = t.project.strip()
    match = project_index.get(project_name.lower()) if project_name else None
    prompt_val = html.escape(t.name or "", quote=True)
    actions: list[str] = []
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

    source_val = (t.source or "").strip()
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


def render_notion_sidebar(
    todos: list[NotionTodo], source: str, fetched_at: str | None,
    project_index: dict, known_sids: set,
) -> str:
    today = dt.date.today()
    overdue = 0
    today_count = 0
    groups: dict[str, list[NotionTodo]] = {}
    for t in todos:
        key = (t.project or "").strip() or "Unassigned"
        groups.setdefault(key, []).append(t)
    group_blocks: list[str] = []
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
                t2 = dt.datetime.fromisoformat(fetched_at)
                ts_str = f" · {t2.astimezone().strftime('%b %d %H:%M')}"
            except ValueError:
                ts_str = f" · {fetched_at[:16]}"
        src_note = f'<span class="src stale">cached{ts_str}</span>'
    else:
        src_note = '<span class="src none">no token</span>'

    counts: list[str] = []
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
