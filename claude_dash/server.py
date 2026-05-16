from __future__ import annotations

import asyncio
import datetime as dt
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, indexer, launcher, notion
from .config import HOST, PORT
from .events import bus
from .models import UsageTotals
from .subscription import load_subscription_usage

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"
WEB_INDEX = WEB_DIST / "index.html"

app = FastAPI(title="claude-dash", docs_url=None, redoc_url=None)


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


def _resolve_range(qs) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    date_p = _parse_date(qs.get("date"))
    if date_p:
        return date_p, date_p
    end_d = _parse_date(qs.get("to")) or today
    start_d = _parse_date(qs.get("from")) or end_d
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    return start_d, end_d


def _dashboard_payload(qs) -> dict:
    today = dt.date.today()
    start_d, end_d = _resolve_range(qs)
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
    project_index = db.build_project_index(week_sessions)
    known_sids = sorted({s.session_id for s in week_sessions})

    cwds = sorted({s.cwd for s in range_sessions})
    projects: dict[str, dict] = {}
    for cwd in cwds:
        group = [s for s in range_sessions if s.cwd == cwd]
        projects[cwd] = {
            "cwd": cwd,
            "name": Path(cwd).name or cwd,
            "github_url": launcher.get_github_url(cwd),
            "augment_status": launcher.get_augment_status(cwd),
            "session_count": len(group),
            "open_tasks": sum(len(s.incomplete_tasks) for s in group),
        }
    total_open = sum(p["open_tasks"] for p in projects.values())

    span_days = (end_d - start_d).days + 1
    is_today_only = start_d == today and end_d == today
    is_single_day = start_d == end_d
    if is_single_day:
        range_label = "today" if start_d == today else start_d.isoformat()
    else:
        range_label = f"{start_d.isoformat()} → {end_d.isoformat()} ({span_days}d)"

    sessions_out: list[dict] = []
    for s in range_sessions:
        d = s.model_dump(
            mode="json",
            exclude={"path", "all_messages", "user_prompts"},
        )
        d["incomplete_count"] = len(s.incomplete_tasks)
        d["completed_count"] = len(s.completed_tasks)
        sessions_out.append(d)

    return {
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "range_label": range_label,
        "is_today_only": is_today_only,
        "is_single_day": is_single_day,
        "sessions": sessions_out,
        "projects": projects,
        "project_index": project_index,
        "today_usage": today_usage.model_dump(),
        "week_usage": week_usage.model_dump(),
        "range_usage": range_usage.model_dump(),
        "total_open": total_open,
        "known_sids": known_sids,
    }


# --- JSON API ---

@app.get("/api/dashboard")
async def api_dashboard(request: Request) -> JSONResponse:
    return JSONResponse(_dashboard_payload(request.query_params))


@app.get("/api/todos")
async def api_todos() -> JSONResponse:
    r = notion.load_todos()
    return JSONResponse({
        "todos": [t.model_dump() for t in r.todos],
        "source": r.source,
        "fetched_at": r.fetched_at,
    })


@app.get("/api/search")
async def api_search(q: str = "") -> JSONResponse:
    q = q.strip()
    if not q:
        return JSONResponse([])
    return JSONResponse([r.model_dump() for r in db.search(q)])


@app.get("/api/subscription-usage")
async def api_subscription() -> JSONResponse:
    sub = load_subscription_usage()
    return JSONResponse(sub.model_dump() if sub else None)


@app.post("/api/refresh-notion")
async def api_refresh_notion() -> dict:
    ok = notion.refresh_cache()
    return {"ok": ok}


class _StartReq(BaseModel):
    cwd: str
    prompt: str = ""


class _ResumeReq(BaseModel):
    sid: str
    cwd: str
    prompt: str = ""


@app.post("/api/start")
async def api_start(req: _StartReq) -> dict:
    cwd = req.cwd.strip()
    if not cwd:
        return {"ok": False, "message": "missing cwd"}
    ok, info = launcher.start_session(cwd, req.prompt)
    return {"ok": ok, "message": info}


@app.post("/api/resume")
async def api_resume(req: _ResumeReq) -> dict:
    sid = req.sid.strip()
    cwd = req.cwd.strip()
    if not sid or not cwd:
        return {"ok": False, "message": "missing sid or cwd"}
    ok, info = launcher.resume_session(sid, cwd, req.prompt)
    return {"ok": ok, "message": info}


@app.get("/api/open-finder")
async def api_open_finder(cwd: str = "") -> dict:
    ok, info = launcher.open_finder(cwd)
    return {"ok": ok, "message": info}


@app.get("/api/open-terminal")
async def api_open_terminal(cwd: str = "") -> dict:
    ok, info = launcher.start_session(cwd, "")
    return {"ok": ok, "message": info}


@app.get("/api/open-editor")
async def api_open_editor(cwd: str = "") -> dict:
    ok, info = launcher.open_editor(cwd)
    return {"ok": ok, "message": info}


@app.get("/api/augment-index")
async def api_augment_index(cwd: str = "") -> dict:
    ok, info = launcher.trigger_augment_index(cwd)
    return {"ok": ok, "message": info}


@app.get("/api/events")
async def api_events(request: Request) -> StreamingResponse:
    queue = bus.subscribe()

    async def gen():
        try:
            yield "event: open\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- SPA static + fallback ---

if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")


@app.get("/")
def root() -> Response:
    if WEB_INDEX.exists():
        return FileResponse(WEB_INDEX)
    raise HTTPException(
        status_code=503,
        detail="web/dist not built — run `npm install && npm run build` in web/",
    )


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str) -> Response:
    if full_path.startswith("api/") or full_path.startswith("assets/"):
        raise HTTPException(status_code=404)
    if WEB_INDEX.exists():
        return FileResponse(WEB_INDEX)
    raise HTTPException(status_code=404)


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
