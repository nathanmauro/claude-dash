from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

TaskStatus = Literal["pending", "in_progress", "completed"]


class Task(BaseModel):
    task_id: str
    subject: str = ""
    description: str = ""
    status: TaskStatus = "pending"


class Session(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    project_dir: str
    cwd: str
    path: Path
    start_ts: dt.datetime | None = None
    end_ts: dt.datetime | None = None
    title: str = ""
    first_prompt: str = ""
    last_prompt: str = ""
    user_prompts: list[str] = Field(default_factory=list)
    all_messages: list[tuple[str, str]] = Field(default_factory=list)
    tasks: dict[str, Task] = Field(default_factory=dict)
    user_msg_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_create_tokens: int = 0
    cache_read_tokens: int = 0

    @computed_field
    @property
    def billable_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_create_tokens

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.billable_tokens + self.cache_read_tokens

    @property
    def incomplete_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status != "completed"]

    @property
    def completed_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status == "completed"]


class UsageTotals(BaseModel):
    input: int = 0
    output: int = 0
    cache_create: int = 0
    cache_read: int = 0
    billable: int = 0
    total: int = 0
    cache_hit_pct: float = 0.0
    session_count: int = 0

    @classmethod
    def from_sessions(cls, sessions: list[Session]) -> "UsageTotals":
        inp = sum(s.input_tokens for s in sessions)
        out = sum(s.output_tokens for s in sessions)
        cc = sum(s.cache_create_tokens for s in sessions)
        cr = sum(s.cache_read_tokens for s in sessions)
        denom = cr + cc + inp
        return cls(
            input=inp,
            output=out,
            cache_create=cc,
            cache_read=cr,
            billable=inp + out + cc,
            total=inp + out + cc + cr,
            cache_hit_pct=(100.0 * cr / denom) if denom else 0.0,
            session_count=len(sessions),
        )


class NotionTodo(BaseModel):
    name: str = ""
    status: str = ""
    due: str | None = None
    url: str | None = None
    project: str = ""
    source: str = ""


class NotionTodosResult(BaseModel):
    todos: list[NotionTodo] = Field(default_factory=list)
    source: Literal["live", "cache", "none"] = "none"
    fetched_at: str | None = None


class RateLimit(BaseModel):
    used_percentage: float | None = None
    resets_at: int | float | str | None = None
    reset_at: int | float | str | None = None


class RateLimits(BaseModel):
    five_hour: RateLimit | None = None
    seven_day: RateLimit | None = None
    seven_day_opus: RateLimit | None = None
    seven_day_sonnet: RateLimit | None = None


class SubscriptionCost(BaseModel):
    total_cost_usd: float | None = None


class SubscriptionUsage(BaseModel):
    rate_limits: RateLimits | None = None
    cost: SubscriptionCost | None = None


class SearchResult(BaseModel):
    session_id: str
    title: str
    snippet: str
    cwd: str
    date: str = ""


class ProjectMeta(BaseModel):
    cwd: str
    github_url: str | None = None
    notion_page_id: str | None = None
    augment_indexed_at: str | None = None
    editor: str | None = None
