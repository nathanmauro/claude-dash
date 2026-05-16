export type TaskStatus = "pending" | "in_progress" | "completed";

export interface Task {
  task_id: string;
  subject: string;
  description: string;
  status: TaskStatus;
}

export interface SessionData {
  session_id: string;
  project_dir: string;
  cwd: string;
  start_ts: string | null;
  end_ts: string | null;
  title: string;
  first_prompt: string;
  last_prompt: string;
  tasks: Record<string, Task>;
  user_msg_count: number;
  input_tokens: number;
  output_tokens: number;
  cache_create_tokens: number;
  cache_read_tokens: number;
  billable_tokens: number;
  total_tokens: number;
  incomplete_count: number;
  completed_count: number;
}

export interface UsageTotals {
  input: number;
  output: number;
  cache_create: number;
  cache_read: number;
  billable: number;
  total: number;
  cache_hit_pct: number;
  session_count: number;
}

export interface ProjectInfo {
  cwd: string;
  name: string;
  github_url: string | null;
  augment_status: string;
  session_count: number;
  open_tasks: number;
}

export interface DashboardResponse {
  start: string;
  end: string;
  range_label: string;
  is_today_only: boolean;
  is_single_day: boolean;
  sessions: SessionData[];
  projects: Record<string, ProjectInfo>;
  project_index: Record<string, [string, string]>;
  today_usage: UsageTotals;
  week_usage: UsageTotals;
  range_usage: UsageTotals;
  total_open: number;
  known_sids: string[];
}

export interface NotionTodo {
  name: string;
  status: string;
  due: string | null;
  url: string | null;
  project: string;
  source: string;
}

export interface NotionTodosResponse {
  todos: NotionTodo[];
  source: "live" | "cache" | "none";
  fetched_at: string | null;
}

export interface SearchHit {
  session_id: string;
  title: string;
  snippet: string;
  cwd: string;
  date: string;
}

export interface RateLimit {
  used_percentage: number | null;
  resets_at: number | string | null;
  reset_at: number | string | null;
}

export interface SubscriptionUsage {
  rate_limits: {
    five_hour: RateLimit | null;
    seven_day: RateLimit | null;
    seven_day_opus: RateLimit | null;
    seven_day_sonnet: RateLimit | null;
  } | null;
  cost: { total_cost_usd: number | null } | null;
}

export interface ActionResult {
  ok: boolean;
  message?: string;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  dashboard: (q: { from?: string; to?: string; date?: string }) => {
    const usp = new URLSearchParams();
    if (q.date) usp.set("date", q.date);
    if (q.from) usp.set("from", q.from);
    if (q.to) usp.set("to", q.to);
    const qs = usp.toString();
    return getJSON<DashboardResponse>(`/api/dashboard${qs ? "?" + qs : ""}`);
  },
  todos: () => getJSON<NotionTodosResponse>("/api/todos"),
  search: (q: string) =>
    getJSON<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}`),
  subscription: () => getJSON<SubscriptionUsage | null>("/api/subscription-usage"),
  refreshNotion: () => postJSON<{ ok: boolean }>("/api/refresh-notion"),
  start: (cwd: string, prompt = "") =>
    postJSON<ActionResult>("/api/start", { cwd, prompt }),
  resume: (sid: string, cwd: string, prompt = "") =>
    postJSON<ActionResult>("/api/resume", { sid, cwd, prompt }),
  openFinder: (cwd: string) =>
    getJSON<ActionResult>(`/api/open-finder?cwd=${encodeURIComponent(cwd)}`),
  openTerminal: (cwd: string) =>
    getJSON<ActionResult>(`/api/open-terminal?cwd=${encodeURIComponent(cwd)}`),
  openEditor: (cwd: string) =>
    getJSON<ActionResult>(`/api/open-editor?cwd=${encodeURIComponent(cwd)}`),
  augmentIndex: (cwd: string) =>
    getJSON<ActionResult>(`/api/augment-index?cwd=${encodeURIComponent(cwd)}`),
};
