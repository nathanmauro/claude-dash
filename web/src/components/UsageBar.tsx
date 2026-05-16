import type { DashboardResponse, RateLimit, SubscriptionUsage } from "../api";
import { fmtTokens, pluralS } from "../utils/format";
import { useSubscription } from "../hooks/useSubscription";

interface Props {
  data: DashboardResponse;
}

function rateClass(pct: number): "good" | "warn" | "bad" {
  if (pct >= 90) return "bad";
  if (pct >= 70) return "warn";
  return "good";
}

function resetCountdown(rl: RateLimit): string {
  const v = rl.resets_at ?? rl.reset_at;
  if (v == null) return "";
  let target: Date;
  try {
    if (typeof v === "number" || (typeof v === "string" && /^\d+(\.\d+)?$/.test(v))) {
      target = new Date(Number(v) * 1000);
    } else {
      target = new Date(String(v).replace("Z", "+00:00"));
    }
  } catch {
    return "";
  }
  const secs = Math.floor((target.getTime() - Date.now()) / 1000);
  if (secs <= 0) return "reset due";
  if (secs >= 86400) return `resets in ${Math.floor(secs / 86400)}d ${Math.floor((secs % 86400) / 3600)}h`;
  if (secs >= 3600) return `resets in ${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
  return `resets in ${Math.floor(secs / 60)}m`;
}

function RateBlock({ label, rl }: { label: string; rl: RateLimit | null | undefined }) {
  if (!rl || rl.used_percentage == null) return null;
  const pct = Number(rl.used_percentage);
  if (Number.isNaN(pct)) return null;
  const cls = rateClass(pct);
  return (
    <div className="usage-block">
      <div className="lbl">{label}</div>
      <div className={`val ${cls}`}>{pct.toFixed(0)}%</div>
      <div className="sub">{resetCountdown(rl)}</div>
    </div>
  );
}

export function UsageBar({ data }: Props) {
  const sub = useSubscription().data as SubscriptionUsage | null | undefined;
  const today_u = data.today_usage;
  const range_u = data.range_usage;
  const week_u = data.week_usage;
  const cost = sub?.cost?.total_cost_usd;
  const costStr = typeof cost === "number" ? `$${cost.toFixed(2)}` : "";

  const first = data.is_today_only ? (
    <div className="usage-block">
      <div className="lbl">Today</div>
      <div className="val">{fmtTokens(today_u.billable)}</div>
      <div className="sub">
        {today_u.session_count} session{pluralS(today_u.session_count)}
        {costStr && ` · ${costStr}`}
      </div>
    </div>
  ) : (
    <div className="usage-block">
      <div className="lbl">Range</div>
      <div className="val">{fmtTokens(range_u.billable)}</div>
      <div className="sub">
        {range_u.session_count} session{pluralS(range_u.session_count)} · {data.range_label}
      </div>
    </div>
  );

  const rl = sub?.rate_limits;
  return (
    <div className="usage">
      {first}
      <div className="usage-block">
        <div className="lbl">Last 7d</div>
        <div className="val">{fmtTokens(week_u.billable)}</div>
        <div className="sub">
          {week_u.session_count} session{pluralS(week_u.session_count)}
        </div>
      </div>
      <div className="usage-block">
        <div className="lbl">Cache hit</div>
        <div className="val">{today_u.cache_hit_pct.toFixed(0)}%</div>
        <div className="sub">{fmtTokens(today_u.cache_read)} cached today</div>
      </div>
      {rl && (
        <>
          <RateBlock label="5h limit" rl={rl.five_hour} />
          <RateBlock label="7d limit" rl={rl.seven_day} />
          <RateBlock label="7d Opus" rl={rl.seven_day_opus} />
          <RateBlock label="7d Sonnet" rl={rl.seven_day_sonnet} />
        </>
      )}
    </div>
  );
}
