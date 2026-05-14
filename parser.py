from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

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
    all_messages: list[tuple[str, str]] = field(default_factory=list) # (role, content)
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
    if not s: return None
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError: return None

def extract_text(content) -> str:
    if isinstance(content, str): return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(c.get("text", ""))
        return "\n".join(out)
    return ""

def is_real_user_prompt(text: str) -> bool:
    if not text: return False
    t = text.strip()
    if not t or t.startswith("<command-") or t.startswith("<local-command-") or \
       t.startswith("<system-reminder") or "Messages below were generated" in t:
        return False
    return True

def parse_session(path: Path):
    project_dir = path.parent.name
    sess = Session(session_id=path.stem, project_dir=project_dir, cwd=decode_project_dir(project_dir), path=path)
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try: j = json.loads(line)
                except json.JSONDecodeError: continue
                t = j.get("type")
                if j.get("cwd"): sess.cwd = j["cwd"]
                ts = parse_ts(j.get("timestamp"))
                if ts:
                    if sess.start_ts is None or ts < sess.start_ts: sess.start_ts = ts
                    if sess.end_ts is None or ts > sess.end_ts: sess.end_ts = ts
                if t == "ai-title":
                    sess.title = j.get("aiTitle", "") or sess.title
                elif t == "user" and not j.get("isSidechain") and not j.get("isMeta"):
                    text = extract_text((j.get("message") or {}).get("content", ""))
                    if text:
                        sess.all_messages.append(("user", text))
                    if is_real_user_prompt(text):
                        sess.user_msg_count += 1
                        snippet = text.strip()
                        if not sess.first_prompt: sess.first_prompt = snippet
                        sess.last_prompt = snippet
                        if len(sess.user_prompts) < 50: sess.user_prompts.append(snippet)
                elif t == "assistant" and not j.get("isSidechain"):
                    msg = j.get("message", {}) or {}
                    text = extract_text(msg.get("content", ""))
                    if text:
                        sess.all_messages.append(("assistant", text))
                    usage = msg.get("usage") or {}
                    sess.input_tokens += usage.get("input_tokens", 0) or 0
                    sess.output_tokens += usage.get("output_tokens", 0) or 0
                    sess.cache_create_tokens += usage.get("cache_creation_input_tokens", 0) or 0
                    sess.cache_read_tokens += usage.get("cache_read_input_tokens", 0) or 0
                    for c in msg.get("content", []):
                        if not isinstance(c, dict) or c.get("type") != "tool_use": continue
                        name, inp = c.get("name"), c.get("input", {}) or {}
                        if name == "TaskCreate":
                            tid = str(inp.get("taskId") or len(sess.tasks) + 1)
                            sess.tasks[tid] = Task(tid, inp.get("subject", ""), inp.get("description", ""))
                        elif name == "TaskUpdate":
                            tid = str(inp.get("taskId", ""))
                            if tid in sess.tasks and inp.get("status"):
                                sess.tasks[tid].status = inp["status"]
    except OSError: return None
    return sess if sess.start_ts else None
