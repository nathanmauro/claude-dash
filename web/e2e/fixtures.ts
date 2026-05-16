import { test as base, expect, type Page } from "@playwright/test";
import type {
  DashboardResponse,
  NotionTodo,
  NotionTodosResponse,
  ProjectInfo,
  SearchHit,
  SessionData,
  SubscriptionUsage,
  UsageTotals,
} from "../src/api";

export const TODAY = new Date().toISOString().slice(0, 10);

export function shiftDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export const PROJECT_CWD = "/Users/test/proj/example";
export const PROJECT_NAME = "example";

export function emptyUsage(overrides: Partial<UsageTotals> = {}): UsageTotals {
  return {
    input: 0,
    output: 0,
    cache_create: 0,
    cache_read: 0,
    billable: 0,
    total: 0,
    cache_hit_pct: 0,
    session_count: 0,
    ...overrides,
  };
}

export function makeSession(overrides: Partial<SessionData> = {}): SessionData {
  const sid = overrides.session_id ?? "sess-aaa";
  return {
    session_id: sid,
    project_dir: PROJECT_CWD,
    cwd: PROJECT_CWD,
    start_ts: `${TODAY}T10:00:00`,
    end_ts: `${TODAY}T10:30:00`,
    title: "Migration to FastAPI",
    first_prompt: "Help me plan the migration from Flask to FastAPI",
    last_prompt: "Looks good, ship it",
    tasks: {
      "t-1": {
        task_id: "t-1",
        subject: "Wire up the routes",
        description: "",
        status: "in_progress",
      },
    },
    user_msg_count: 4,
    input_tokens: 1000,
    output_tokens: 500,
    cache_create_tokens: 0,
    cache_read_tokens: 0,
    billable_tokens: 1500,
    total_tokens: 1500,
    incomplete_count: 1,
    completed_count: 0,
    ...overrides,
  };
}

export function makeProject(overrides: Partial<ProjectInfo> = {}): ProjectInfo {
  return {
    cwd: PROJECT_CWD,
    name: PROJECT_NAME,
    github_url: null,
    augment_status: "unknown",
    session_count: 1,
    open_tasks: 1,
    ...overrides,
  };
}

export function makeDashboard(
  overrides: Partial<DashboardResponse> = {},
): DashboardResponse {
  const sessions = overrides.sessions ?? [makeSession()];
  const projects = overrides.projects ?? { [PROJECT_CWD]: makeProject() };
  return {
    start: TODAY,
    end: TODAY,
    range_label: "today",
    is_today_only: true,
    is_single_day: true,
    sessions,
    projects,
    project_index: {},
    today_usage: emptyUsage({ billable: 1500, session_count: 1 }),
    week_usage: emptyUsage({ billable: 1500, session_count: 1 }),
    range_usage: emptyUsage({ billable: 1500, session_count: 1 }),
    total_open: 1,
    known_sids: sessions.map((s) => s.session_id),
    ...overrides,
  };
}

export function makeTodo(overrides: Partial<NotionTodo> = {}): NotionTodo {
  return {
    name: "Write the docs",
    status: "Not started",
    due: null,
    url: "https://notion.so/abc",
    project: PROJECT_NAME,
    source: "claude",
    ...overrides,
  };
}

export function makeTodos(
  overrides: Partial<NotionTodosResponse> = {},
): NotionTodosResponse {
  return {
    todos: [makeTodo()],
    source: "cache",
    fetched_at: `${TODAY}T08:00:00`,
    ...overrides,
  };
}

export function makeSearchHits(): SearchHit[] {
  return [
    {
      session_id: "sess-aaa",
      title: "Migration to FastAPI",
      snippet: "plan the <b>migration</b> from Flask to FastAPI",
      cwd: PROJECT_CWD,
      date: TODAY,
    },
    {
      session_id: "sess-bbb",
      title: "Database migration notes",
      snippet: "running the database <b>migration</b> on staging",
      cwd: PROJECT_CWD,
      date: TODAY,
    },
  ];
}

export interface ApiState {
  dashboard: DashboardResponse;
  todos: NotionTodosResponse;
  search: SearchHit[];
  subscription: SubscriptionUsage | null;
  events: string;
  resumeBodies: Array<{ sid: string; cwd: string; prompt: string }>;
  startBodies: Array<{ cwd: string; prompt: string }>;
  refreshNotionCount: number;
  dashboardRequests: number;
  todosRequests: number;
  searchRequests: string[];
}

interface Fixtures {
  api: ApiState;
}

export const test = base.extend<Fixtures>({
  api: async ({ page }, use) => {
    const state: ApiState = {
      dashboard: makeDashboard(),
      todos: makeTodos(),
      search: [],
      subscription: null,
      events: "",
      resumeBodies: [],
      startBodies: [],
      refreshNotionCount: 0,
      dashboardRequests: 0,
      todosRequests: 0,
      searchRequests: [],
    };

    await page.route("**/api/dashboard*", async (route) => {
      state.dashboardRequests++;
      await route.fulfill({
        json: state.dashboard,
        headers: { "Cache-Control": "no-store" },
      });
    });
    await page.route("**/api/todos", async (route) => {
      state.todosRequests++;
      await route.fulfill({
        json: state.todos,
        headers: { "Cache-Control": "no-store" },
      });
    });
    await page.route("**/api/search*", async (route) => {
      const url = new URL(route.request().url());
      state.searchRequests.push(url.searchParams.get("q") ?? "");
      await route.fulfill({ json: state.search });
    });
    await page.route("**/api/subscription-usage", (route) =>
      route.fulfill({ json: state.subscription }),
    );
    await page.route("**/api/events", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "X-Accel-Buffering": "no",
        },
        body: state.events || ": keepalive\n\n",
      }),
    );
    await page.route("**/api/refresh-notion", async (route) => {
      state.refreshNotionCount++;
      await route.fulfill({ json: { ok: true } });
    });
    await page.route("**/api/start", async (route) => {
      state.startBodies.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true, message: "started" } });
    });
    await page.route("**/api/resume", async (route) => {
      state.resumeBodies.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true, message: "resumed" } });
    });
    await page.route(/\/api\/open-(finder|terminal|editor)\?/, (route) =>
      route.fulfill({ json: { ok: true } }),
    );
    await page.route("**/api/augment-index*", (route) =>
      route.fulfill({ json: { ok: true } }),
    );

    await use(state);
  },
});

export { expect };

export async function gotoDashboard(page: Page, query = ""): Promise<void> {
  await page.goto(`/${query}`);
  await page.getByRole("heading", { level: 3 }).first().waitFor();
}
