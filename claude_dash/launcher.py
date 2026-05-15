from __future__ import annotations

import datetime as dt
import json
import shlex
import subprocess
import threading
from pathlib import Path

from . import db
from .config import AUGGIE_BIN


def _terminal_run(cmd: str) -> tuple[bool, str]:
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


def start_session(cwd: str, prompt: str = "") -> tuple[bool, str]:
    if not Path(cwd).exists():
        return False, f"cwd does not exist: {cwd}"
    cmd = f"cd {shlex.quote(cwd)} && claude"
    if prompt.strip():
        cmd += f" {shlex.quote(prompt.strip())}"
    return _terminal_run(cmd)


def resume_session(session_id: str, cwd: str, prompt: str = "") -> tuple[bool, str]:
    if not Path(cwd).exists():
        return False, f"cwd does not exist: {cwd}"
    parts = [
        f"cd {shlex.quote(cwd)}",
        f"claude --resume {shlex.quote(session_id)}",
    ]
    if prompt.strip():
        parts[-1] += f" {shlex.quote(prompt.strip())}"
    return _terminal_run(" && ".join(parts))


def open_finder(cwd: str) -> tuple[bool, str]:
    try:
        subprocess.run(["open", cwd], check=True)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def open_editor(cwd: str) -> tuple[bool, str]:
    for cmd in ("cursor", "code"):
        try:
            subprocess.run([cmd, cwd], check=True)
            return True, f"opened with {cmd}"
        except FileNotFoundError:
            continue
        except Exception as e:
            return False, str(e)
    return False, "cursor/code not found in PATH"


def _augment_index_worker(cwd: str) -> None:
    try:
        subprocess.run([AUGGIE_BIN, "index", "--print"], cwd=cwd, check=True)
        db.set_augment_indexed_at(cwd, dt.datetime.now().isoformat())
    except Exception as e:
        print(f"Augment index error: {e}")


def trigger_augment_index(cwd: str) -> tuple[bool, str]:
    threading.Thread(target=_augment_index_worker, args=(cwd,), daemon=True).start()
    return True, "indexing started"


def get_github_url(cwd: str) -> str | None:
    config = Path(cwd) / ".git" / "config"
    if not config.exists():
        return None
    try:
        for line in config.read_text().splitlines():
            if "url =" in line:
                url = line.split("=", 1)[1].strip()
                if url.startswith("git@github.com:"):
                    return "https://github.com/" + url[15:].replace(".git", "")
                if url.startswith("https://github.com/"):
                    return url.replace(".git", "")
    except OSError:
        pass
    return None


def get_augment_status(cwd: str) -> str:
    when = db.get_augment_indexed_at(cwd)
    if when:
        return f"indexed at {when[:16]}"
    if (Path(cwd) / ".augment").exists():
        return "indexed"
    return "not indexed"
