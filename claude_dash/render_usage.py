from __future__ import annotations

import datetime as dt
import html
import json

from .config import USAGE_FILE
from .models import RateLimit, SubscriptionUsage, UsageTotals
from .views import fmt_tokens


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


def _rate_block(label: str, rl: RateLimit | None) -> str:
    if not rl or rl.used_percentage is None:
        return ""
    try:
        pct_f = float(rl.used_percentage)
    except (TypeError, ValueError):
        return ""
    cls = "good"
    if pct_f >= 90:
        cls = "bad"
    elif pct_f >= 70:
        cls = "warn"
    resets = rl.resets_at if rl.resets_at is not None else rl.reset_at
    reset_str = ""
    if resets is not None:
        try:
            if isinstance(resets, (int, float)) or (isinstance(resets, str) and resets.isdigit()):
                r = dt.datetime.fromtimestamp(float(resets), tz=dt.timezone.utc)
            else:
                r = dt.datetime.fromisoformat(str(resets).replace("Z", "+00:00"))
            now = dt.datetime.now(dt.timezone.utc)
            secs = int((r - now).total_seconds())
            if secs > 0:
                if secs >= 86400:
                    reset_str = f"resets in {secs // 86400}d {(secs % 86400) // 3600}h"
                elif secs >= 3600:
                    reset_str = f"resets in {secs // 3600}h {(secs % 3600) // 60}m"
                else:
                    reset_str = f"resets in {secs // 60}m"
            else:
                reset_str = "reset due"
        except (ValueError, TypeError):
            reset_str = ""
    return f"""
      <div class="usage-block">
        <div class="lbl">{label}</div>
        <div class="val {cls}">{pct_f:.0f}%</div>
        <div class="sub">{reset_str}</div>
      </div>
    """


def render_usage_header(
    today_u: UsageTotals, week_u: UsageTotals, range_u: UsageTotals,
    range_label: str, is_today_only: bool, sub: SubscriptionUsage | None,
) -> str:
    sub_blocks = ""
    if sub and sub.rate_limits:
        rl = sub.rate_limits
        sub_blocks = (
            _rate_block("5h limit", rl.five_hour)
            + _rate_block("7d limit", rl.seven_day)
            + _rate_block("7d Opus", rl.seven_day_opus)
            + _rate_block("7d Sonnet", rl.seven_day_sonnet)
        )
    cost = ""
    if sub and sub.cost and sub.cost.total_cost_usd is not None:
        try:
            cost = f"${float(sub.cost.total_cost_usd):.2f}"
        except (TypeError, ValueError):
            pass
    cost_sub = f" · {cost}" if cost else ""

    if is_today_only:
        first_block = f"""
      <div class="usage-block">
        <div class="lbl">Today</div>
        <div class="val">{fmt_tokens(today_u.billable)}</div>
        <div class="sub">{today_u.session_count} session{'s' if today_u.session_count != 1 else ''}{cost_sub}</div>
      </div>"""
    else:
        first_block = f"""
      <div class="usage-block">
        <div class="lbl">Range</div>
        <div class="val">{fmt_tokens(range_u.billable)}</div>
        <div class="sub">{range_u.session_count} session{'s' if range_u.session_count != 1 else ''} · {html.escape(range_label)}</div>
      </div>"""
    return f"""
    <div class="usage">{first_block}
      <div class="usage-block">
        <div class="lbl">Last 7d</div>
        <div class="val">{fmt_tokens(week_u.billable)}</div>
        <div class="sub">{week_u.session_count} session{'s' if week_u.session_count != 1 else ''}</div>
      </div>
      <div class="usage-block">
        <div class="lbl">Cache hit</div>
        <div class="val">{today_u.cache_hit_pct:.0f}%</div>
        <div class="sub">{fmt_tokens(today_u.cache_read)} cached today</div>
      </div>
      {sub_blocks}
    </div>
    """
