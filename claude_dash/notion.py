from __future__ import annotations

import datetime as dt
import json
import os
import subprocess

import httpx

from .config import (
    KEYCHAIN_ACCOUNT,
    KEYCHAIN_SERVICE,
    NOTION_API,
    NOTION_CACHE_FILE,
    NOTION_DB_ID,
    NOTION_VERSION,
    DASH_CACHE,
)
from .models import NotionTodo, NotionTodosResult


def get_token() -> str | None:
    env = os.environ.get("NOTION_TOKEN")
    if env:
        return env
    try:
        r = subprocess.run(
            ["security", "find-generic-password",
             "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _prop_text(props: dict, name: str) -> str:
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


def _todo_from_row(r: dict) -> NotionTodo:
    props = r.get("properties", {}) or {}
    title_arr = (props.get("Task name", {}) or {}).get("title", []) or []
    name = "".join(t.get("plain_text", "") for t in title_arr)
    status = ((props.get("Status", {}) or {}).get("status") or {}).get("name", "")
    due = ((props.get("Due date", {}) or {}).get("date") or {}).get("start")
    return NotionTodo(
        name=name,
        status=status,
        due=due,
        url=r.get("url"),
        project=_prop_text(props, "Project"),
        source=_prop_text(props, "Source"),
    )


def fetch_todos_live(token: str) -> list[NotionTodo] | None:
    body = {
        "filter": {"or": [
            {"property": "Status", "status": {"equals": "Not started"}},
            {"property": "Status", "status": {"equals": "In progress"}},
        ]},
        "sorts": [{"property": "Due date", "direction": "ascending"}],
        "page_size": 100,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    for endpoint in (
        f"{NOTION_API}/data_sources/{NOTION_DB_ID}/query",
        f"{NOTION_API}/databases/{NOTION_DB_ID}/query",
    ):
        try:
            r = httpx.post(endpoint, json=body, headers=headers, timeout=10.0)
            if r.status_code >= 400:
                continue
            return [_todo_from_row(x) for x in r.json().get("results", [])]
        except httpx.HTTPError:
            continue
    return None


def load_todos() -> NotionTodosResult:
    tok = get_token()
    if tok:
        live = fetch_todos_live(tok)
        if live is not None:
            return NotionTodosResult(todos=live, source="live", fetched_at=None)
    if NOTION_CACHE_FILE.exists():
        try:
            data = json.loads(NOTION_CACHE_FILE.read_text())
            todos = [NotionTodo.model_validate(t) for t in data.get("todos", [])]
            return NotionTodosResult(
                todos=todos, source="cache", fetched_at=data.get("fetched_at")
            )
        except (OSError, json.JSONDecodeError):
            pass
    return NotionTodosResult(todos=[], source="none", fetched_at=None)


def refresh_cache() -> bool:
    tok = get_token()
    if not tok:
        return False
    todos = fetch_todos_live(tok)
    if todos is None:
        return False
    DASH_CACHE.mkdir(parents=True, exist_ok=True)
    NOTION_CACHE_FILE.write_text(json.dumps({
        "fetched_at": dt.datetime.now().astimezone().isoformat(),
        "source": "api",
        "db_id": NOTION_DB_ID,
        "todos": [t.model_dump() for t in todos],
    }, indent=2))
    return True
