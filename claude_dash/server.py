from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db, indexer, launcher, notion
from .config import HOST, PORT
from .models import UsageTotals
from .render_page import render_page
from .render_todos import build_project_index

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="claude-dash", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    indexer.start()


def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    qs = request.query_params
    today = dt.date.today()
    date_p = _parse_date(qs.get("date"))
    if date_p:
        start_d, end_d = date_p, date_p
    else:
        end_d = _parse_date(qs.get("to")) or today
        start_d = _parse_date(qs.get("from")) or end_d
        if start_d > end_d:
            start_d, end_d = end_d, start_d

    week_start = today - dt.timedelta(days=6)
    week_sessions = db.load_sessions(since=week_start)
    today_sessions = [
        s for s in week_sessions
        if s.end_ts and s.end_ts.astimezone().date() == today
    ]
    today_usage = UsageTotals.from_sessions(today_sessions)
    week_usage = UsageTotals.from_sessions(week_sessions)
    if start_d >= week_start and end_d <= today:
        range_sessions = [
            s for s in week_sessions
            if s.end_ts and start_d <= s.end_ts.astimezone().date() <= end_d
        ]
    else:
        range_sessions = db.load_sessions(since=start_d, until=end_d)
    range_usage = UsageTotals.from_sessions(range_sessions)
    todos_res = notion.load_todos()
    project_index = build_project_index(week_sessions)
    known_sids = {s.session_id for s in week_sessions}
    html_body = render_page(
        range_sessions, start_d, end_d,
        todos_res.todos, todos_res.source, todos_res.fetched_at,
        today_usage, week_usage, range_usage, project_index, known_sids,
    )
    return HTMLResponse(html_body)


@app.get("/search")
def search(q: str = "") -> JSONResponse:
    q = q.strip()
    if not q:
        return JSONResponse([])
    results = db.search(q)
    return JSONResponse([r.model_dump() for r in results])


@app.get("/open-finder")
def open_finder(cwd: str = "") -> Response:
    launcher.open_finder(cwd)
    return Response(status_code=204)


@app.get("/open-terminal")
def open_terminal(cwd: str = "") -> Response:
    launcher.start_session(cwd, "")
    return Response(status_code=204)


@app.get("/open-editor")
def open_editor(cwd: str = "") -> Response:
    launcher.open_editor(cwd)
    return Response(status_code=204)


@app.get("/augment/index")
def augment_index(cwd: str = "") -> Response:
    launcher.trigger_augment_index(cwd)
    return Response(status_code=204)


@app.post("/refresh-notion")
def refresh_notion() -> RedirectResponse:
    notion.refresh_cache()
    return RedirectResponse("/", status_code=303)


@app.post("/start")
def start_session(cwd: str = Form(""), prompt: str = Form("")) -> Response:
    cwd = cwd.strip()
    if not cwd:
        return Response(b"missing cwd", status_code=400)
    ok, info = launcher.start_session(cwd, prompt)
    if ok:
        return RedirectResponse("/", status_code=303)
    return Response(info.encode("utf-8"), status_code=500, media_type="text/plain")


@app.post("/resume")
def resume_session(
    sid: str = Form(""), cwd: str = Form(""), prompt: str = Form(""),
) -> Response:
    sid = sid.strip()
    cwd = cwd.strip()
    if not sid or not cwd:
        return Response(b"missing sid or cwd", status_code=400)
    ok, info = launcher.resume_session(sid, cwd, prompt)
    if ok:
        return RedirectResponse("/", status_code=303)
    return Response(info.encode("utf-8"), status_code=500, media_type="text/plain")


def run() -> None:
    import sys
    import uvicorn

    no_open = "--no-open" in sys.argv[1:]
    url = f"http://{HOST}:{PORT}/"
    print(f"Claude dashboard on {url}", flush=True)
    if not no_open:
        try:
            subprocess.Popen(["open", url])
        except Exception:
            pass
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
