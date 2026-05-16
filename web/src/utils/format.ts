export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function pad2(n: number) {
  return n.toString().padStart(2, "0");
}

export function fmtLocal(ts: string | null | undefined): string {
  if (!ts) return "";
  const d = new Date(ts);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtRange(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  const s = new Date(start);
  const e = new Date(end);
  const sameDay =
    s.getFullYear() === e.getFullYear() &&
    s.getMonth() === e.getMonth() &&
    s.getDate() === e.getDate();
  if (sameDay) {
    return `${pad2(s.getHours())}:${pad2(s.getMinutes())}–${pad2(e.getHours())}:${pad2(e.getMinutes())}`;
  }
  return `${MONTHS[s.getMonth()]} ${pad2(s.getDate())} ${pad2(s.getHours())}:${pad2(s.getMinutes())} → ${MONTHS[e.getMonth()]} ${pad2(e.getDate())} ${pad2(e.getHours())}:${pad2(e.getMinutes())}`;
}

export function fmtDuration(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  const secs = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

export function truncate(s: string, n = 180): string {
  const trimmed = (s ?? "").trim().replace(/\n/g, " ");
  return trimmed.length <= n ? trimmed : trimmed.slice(0, n - 1) + "…";
}

export function homeCollapse(p: string): string {
  // We can't read $HOME from the browser; the API includes cwds with the literal
  // home prefix, so substitute the common /Users/<user> pattern. The first
  // /Users/* component is the home — collapse it to "~".
  const m = /^\/Users\/[^/]+/.exec(p);
  return m ? "~" + p.slice(m[0].length) : p;
}

export function fmtBytes(n: number): string {
  return fmtTokens(n);
}

export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return isoDate(d);
}

export function pluralS(n: number): string {
  return n === 1 ? "" : "s";
}
