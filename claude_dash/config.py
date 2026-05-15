from __future__ import annotations

import os
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
DASH_CACHE = Path.home() / ".claude-dash"
DB_PATH = DASH_CACHE / "index.db"
NOTION_CACHE_FILE = DASH_CACHE / "notion-todos.json"
USAGE_FILE = DASH_CACHE / "usage.json"

PORT = int(os.environ.get("CLAUDE_DASH_PORT", "8765"))
HOST = os.environ.get("CLAUDE_DASH_HOST", "127.0.0.1")

NOTION_DB_ID = os.environ.get(
    "TODO_NOTION_DB_ID", "353b9be9-bd58-8049-b5c5-e577f0a49756"
)
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
KEYCHAIN_ACCOUNT = "notion"
KEYCHAIN_SERVICE = "todo-cli"

AUGGIE_BIN = os.environ.get(
    "CLAUDE_DASH_AUGGIE",
    "/Users/nathan/.nvm/versions/node/v26.1.0/bin/auggie",
)

INDEXER_INTERVAL_S = 60
