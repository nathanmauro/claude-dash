import sqlite3
import os
from pathlib import Path
from parser import parse_session

DB_PATH = Path.home() / ".claude-dash" / "index.db"

def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
        # FTS5 Trigram might not be available in all sqlite versions
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    session_id UNINDEXED,
                    role UNINDEXED,
                    content,
                    tokenize='trigram'
                );
            """)
        except sqlite3.OperationalError:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    session_id UNINDEXED,
                    role UNINDEXED,
                    content
                );
            """)

def index_all(projects_dir: Path):
    init_db()
    with get_db() as conn:
        for proj in projects_dir.iterdir():
            if not proj.is_dir(): continue
            for jsonl in proj.glob("*.jsonl"):
                stat = jsonl.stat()
                # Check if already indexed and unchanged
                cur = conn.execute("SELECT mtime, size FROM sessions WHERE session_id = ?", (jsonl.stem,)).fetchone()
                if cur and cur['mtime'] == stat.st_mtime and cur['size'] == stat.st_size:
                    continue
                
                sess = parse_session(jsonl)
                if not sess: continue
                
                conn.execute("DELETE FROM messages_fts WHERE session_id = ?", (sess.session_id,))
                conn.execute("DELETE FROM tasks WHERE session_id = ?", (sess.session_id,))
                conn.execute("""
                    INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    sess.session_id, sess.project_dir, sess.cwd,
                    sess.start_ts.isoformat() if sess.start_ts else None,
                    sess.end_ts.isoformat() if sess.end_ts else None,
                    sess.title, sess.first_prompt, sess.last_prompt,
                    sess.user_msg_count, sess.input_tokens, sess.output_tokens,
                    sess.cache_create_tokens, sess.cache_read_tokens,
                    stat.st_mtime, stat.st_size
                ))
                # Index all messages for search
                for role, content in sess.all_messages:
                    conn.execute("INSERT INTO messages_fts(session_id, role, content) VALUES (?, ?, ?)", (sess.session_id, role, content))

                # Insert tasks
                for t in sess.tasks.values():
                    conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (sess.session_id, t.task_id, t.subject, t.description, t.status))

def search(query: str):
    with get_db() as conn:
        return conn.execute("""
            SELECT s.*, snippet(messages_fts, 2, '<b>', '</b>', '...', 64) as snippet
            FROM messages_fts
            JOIN sessions s ON s.session_id = messages_fts.session_id
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT 50
        """, (query,)).fetchall()
