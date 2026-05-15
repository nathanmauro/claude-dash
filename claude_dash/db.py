from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DB_PATH, PROJECTS_DIR
from .models import SearchResult, Session, Task
from .parser import parse_session, parse_ts


def _row_to_session(r, conn) -> Session:
    sid = r["session_id"]
    task_rows = conn.execute(
        "SELECT * FROM tasks WHERE session_id = ?", (sid,)
    ).fetchall()
    tasks = {
        tr["task_id"]: Task(
            task_id=tr["task_id"],
            subject=tr["subject"] or "",
            description=tr["description"] or "",
            status=tr["status"] or "pending",
        )
        for tr in task_rows
    }
    return Session(
        session_id=sid,
        project_dir=r["project_dir"] or "",
        cwd=r["cwd"] or "",
        path=PROJECTS_DIR / (r["project_dir"] or "") / f"{sid}.jsonl",
        start_ts=parse_ts(r["start_ts"]),
        end_ts=parse_ts(r["end_ts"]),
        title=r["title"] or "",
        first_prompt=r["first_prompt"] or "",
        last_prompt=r["last_prompt"] or "",
        tasks=tasks,
        user_msg_count=r["user_msg_count"] or 0,
        input_tokens=r["input_tokens"] or 0,
        output_tokens=r["output_tokens"] or 0,
        cache_create_tokens=r["cache_create_tokens"] or 0,
        cache_read_tokens=r["cache_read_tokens"] or 0,
    )


def load_sessions(
    on_date=None,
    since=None,
    until=None,
) -> list[Session]:
    import datetime as _dt

    with get_db() as conn:
        q = "SELECT * FROM sessions"
        params: list = []
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
        return [_row_to_session(r, conn) for r in rows]


def get_augment_indexed_at(cwd: str) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT augment_indexed_at FROM project_meta WHERE cwd = ?", (cwd,)
        ).fetchone()
        return row["augment_indexed_at"] if row else None


def set_augment_indexed_at(cwd: str, when: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO project_meta(cwd, augment_indexed_at) VALUES (?, ?)",
            (cwd, when),
        )


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                project_dir TEXT,
                cwd TEXT,
                start_ts TEXT,
                end_ts TEXT,
                title TEXT,
                first_prompt TEXT,
                last_prompt TEXT,
                user_msg_count INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_create_tokens INTEGER,
                cache_read_tokens INTEGER,
                mtime REAL,
                size INTEGER
            );
            CREATE TABLE IF NOT EXISTS tasks (
                session_id TEXT,
                task_id TEXT,
                subject TEXT,
                description TEXT,
                status TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS project_meta (
                cwd TEXT PRIMARY KEY,
                github_url TEXT,
                notion_page_id TEXT,
                augment_indexed_at TEXT,
                editor TEXT
            );
        """)
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    session_id UNINDEXED, role UNINDEXED, content,
                    tokenize='trigram'
                );
            """)
        except sqlite3.OperationalError:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    session_id UNINDEXED, role UNINDEXED, content
                );
            """)


def index_all(projects_dir: Path = PROJECTS_DIR) -> None:
    init_db()
    with get_db() as conn:
        for proj in projects_dir.iterdir():
            if not proj.is_dir():
                continue
            for jsonl in proj.glob("*.jsonl"):
                stat = jsonl.stat()
                cur = conn.execute(
                    "SELECT mtime, size FROM sessions WHERE session_id = ?",
                    (jsonl.stem,),
                ).fetchone()
                if cur and cur["mtime"] == stat.st_mtime and cur["size"] == stat.st_size:
                    continue
                sess = parse_session(jsonl)
                if not sess:
                    continue
                conn.execute("DELETE FROM messages_fts WHERE session_id = ?", (sess.session_id,))
                conn.execute("DELETE FROM tasks WHERE session_id = ?", (sess.session_id,))
                conn.execute(
                    "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sess.session_id, sess.project_dir, sess.cwd,
                        sess.start_ts.isoformat() if sess.start_ts else None,
                        sess.end_ts.isoformat() if sess.end_ts else None,
                        sess.title, sess.first_prompt, sess.last_prompt,
                        sess.user_msg_count, sess.input_tokens, sess.output_tokens,
                        sess.cache_create_tokens, sess.cache_read_tokens,
                        stat.st_mtime, stat.st_size,
                    ),
                )
                for role, content in sess.all_messages:
                    conn.execute(
                        "INSERT INTO messages_fts(session_id, role, content) VALUES (?, ?, ?)",
                        (sess.session_id, role, content),
                    )
                for t in sess.tasks.values():
                    conn.execute(
                        "INSERT INTO tasks VALUES (?,?,?,?,?)",
                        (sess.session_id, t.task_id, t.subject, t.description, t.status),
                    )


def search(query: str, limit: int = 50) -> list[SearchResult]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.session_id, s.title, s.first_prompt, s.cwd, s.start_ts,
                   snippet(messages_fts, 2, '<b>', '</b>', '...', 64) as snippet
            FROM messages_fts
            JOIN sessions s ON s.session_id = messages_fts.session_id
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    out: list[SearchResult] = []
    for r in rows:
        ts = parse_ts(r["start_ts"])
        out.append(SearchResult(
            session_id=r["session_id"],
            title=r["title"] or (r["first_prompt"] or "")[:80] or r["session_id"],
            snippet=r["snippet"] or "",
            cwd=r["cwd"] or "",
            date=ts.strftime("%Y-%m-%d %H:%M") if ts else "",
        ))
    return out
