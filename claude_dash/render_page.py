from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .models import NotionTodo, Session, UsageTotals
from .render_todos import render_notion_sidebar
from .render_usage import load_subscription_usage, render_usage_header
from .views import (
    fmt_tokens,
    home_collapse,
    render_icon_row,
    render_session_card,
)


def render_page(
    sessions: list[Session],
    start_d: dt.date,
    end_d: dt.date,
    notion_todos: list[NotionTodo],
    notion_source: str,
    notion_fetched_at: str | None,
    today_usage: UsageTotals,
    week_usage: UsageTotals,
    range_usage: UsageTotals,
    project_index: dict,
    known_sids: set,
) -> str:
    by_project: dict[str, list[Session]] = {}
    for s in sessions:
        by_project.setdefault(s.cwd, []).append(s)

    project_blocks: list[str] = []
    total_open = 0
    for cwd, group in sorted(
        by_project.items(),
        key=lambda kv: -sum(1 for s in kv[1] if s.incomplete_tasks),
    ):
        open_in_group = sum(len(s.incomplete_tasks) for s in group)
        total_open += open_in_group
        group.sort(
            key=lambda s: (
                0 if s.incomplete_tasks else 1,
                -(s.end_ts.timestamp() if s.end_ts else 0),
            )
        )
        cards = "".join(render_session_card(s) for s in group)
        plural = "s" if len(group) != 1 else ""
        base = Path(cwd).name or cwd
        open_note = (
            f' · <span class="open">{open_in_group} open</span>' if open_in_group else ""
        )
        icons = render_icon_row(cwd, base)
        project_blocks.append(
            f'<section class="project">'
            f'<h2 class="proj-head">'
            f'<span class="proj-base">{html.escape(base)}</span>'
            f'<span class="proj-path">{html.escape(home_collapse(cwd))}</span>'
            f'<span class="proj-meta">{len(group)} session{plural}{open_note}</span>'
            f"{icons}"
            f"</h2>"
            f"{cards}</section>"
        )

    today = dt.date.today()
    is_today_only = start_d == today and end_d == today
    is_single_day = start_d == end_d
    span_days = (end_d - start_d).days + 1

    prev_from = (start_d - dt.timedelta(days=1)).isoformat()
    prev_to = (end_d - dt.timedelta(days=1)).isoformat()
    next_from = (start_d + dt.timedelta(days=1)).isoformat()
    next_to = (end_d + dt.timedelta(days=1)).isoformat()

    q_today = "/"
    q_7d = f"/?from={(today - dt.timedelta(days=6)).isoformat()}&to={today.isoformat()}"
    q_30d = f"/?from={(today - dt.timedelta(days=29)).isoformat()}&to={today.isoformat()}"
    cls_today = "active" if is_today_only else ""
    cls_7d = "active" if (start_d == today - dt.timedelta(days=6) and end_d == today) else ""
    cls_30d = "active" if (start_d == today - dt.timedelta(days=29) and end_d == today) else ""

    if is_single_day:
        range_label = "today" if start_d == today else start_d.isoformat()
    else:
        range_label = f"{start_d.isoformat()} → {end_d.isoformat()} ({span_days}d)"

    open_strong = (
        f' · <strong class="open-count">{total_open} open task'
        f'{"s" if total_open != 1 else ""}</strong>'
        if total_open else ""
    )
    plural_s = "s" if len(sessions) != 1 else ""
    tokens_note = (
        f' · {fmt_tokens(range_usage.billable)} tokens' if range_usage.billable else ""
    )
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
    usage = render_usage_header(
        today_usage, week_usage, range_usage, range_label, is_today_only, sub
    )

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
