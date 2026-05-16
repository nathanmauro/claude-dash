from __future__ import annotations

import json

from .config import USAGE_FILE
from .models import SubscriptionUsage


def load_subscription_usage() -> SubscriptionUsage | None:
    if not USAGE_FILE.exists():
        return None
    try:
        data = json.loads(USAGE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return SubscriptionUsage.model_validate(data)
    except Exception:
        return None
