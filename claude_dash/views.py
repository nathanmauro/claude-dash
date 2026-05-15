from __future__ import annotations

import datetime as dt
import html
import urllib.parse
from pathlib import Path

from .launcher import get_augment_status, get_github_url
from .models import NotionTodo, Session, SubscriptionUsage, UsageTotals

STATUS_LABEL = {"completed": "done", "in_progress": "in-prog", "pending": "todo"}


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_local(ts: dt.datetime | None) -> str:
    return ts.astimezone().strftime("%H:%M") if ts else ""


def fmt_range(start: dt.datetime | None, end: dt.datetime | None) -> str:
    if not start or not end:
        return ""
    s = start.astimezone()
    e = end.astimezone()
    if s.date() == e.date():
        return f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
    return f"{s.strftime('%b %d %H:%M')} → {e.strftime('%b %d %H:%M')}"


def fmt_duration(start: dt.datetime | None, end: dt.datetime | None) -> str:
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
    return s if len(s) <= n else s[: n - 1] + "…"


def home_collapse(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


def render_icon_row(cwd: str, project_name: str) -> str:
    gh_url = get_github_url(cwd)
    notion_url = f"https://www.notion.so/search?q={urllib.parse.quote(project_name)}"
    aug_status = get_augment_status(cwd)
    icons: list[str] = []

    icons.append(f'''
        <a class="icon-btn" href="/open-finder?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
            <span class="tooltip">Finder: {html.escape(home_collapse(cwd))}</span>
        </a>
    ''')
    icons.append(f'''
        <a class="icon-btn" href="/open-terminal?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
            <span class="tooltip">Terminal</span>
        </a>
    ''')
    icons.append(f'''
        <a class="icon-btn" href="/open-editor?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/></svg>
            <span class="tooltip">Editor (Cursor)</span>
        </a>
    ''')
    if gh_url:
        icons.append(f'''
            <a class="icon-btn" href="{gh_url}" target="_blank">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></svg>
                <span class="tooltip">GitHub: {html.escape(gh_url.split('/')[-1])}</span>
            </a>
        ''')
    icons.append(f'''
        <a class="icon-btn" href="{notion_url}" target="_blank">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/><line x1="9" y1="11" x2="15" y2="11"/><line x1="9" y1="19" x2="13" y2="19"/></svg>
            <span class="tooltip">Notion Project</span>
        </a>
    ''')
    aug_cls = "ok" if aug_status == "indexed" else ""
    icons.append(f'''
        <a class="icon-btn {aug_cls}" href="/augment/index?cwd={urllib.parse.quote(cwd)}" target="hidden-frame">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/><path d="M12 6v6l4 2"/></svg>
            <span class="tooltip">Augment: {aug_status} (Click to index)</span>
        </a>
    ''')
    return f'<div class="icon-row">{"".join(icons)}<iframe name="hidden-frame" style="display:none"></iframe></div>'


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
