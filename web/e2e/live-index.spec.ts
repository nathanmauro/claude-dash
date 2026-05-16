import {
  expect,
  gotoDashboard,
  makeDashboard,
  makeSession,
  test,
} from "./fixtures";

test("SSE indexed event triggers a dashboard refetch without reload", async ({
  page,
  api,
}) => {
  const initial = api.dashboard;
  const withExtra = makeDashboard({
    sessions: [
      ...initial.sessions,
      makeSession({
        session_id: "sess-bbb",
        title: "Just appeared",
        incomplete_count: 0,
        completed_count: 0,
        tasks: {},
        first_prompt: "freshly indexed session",
        last_prompt: "freshly indexed session",
      }),
    ],
    known_sids: [...initial.known_sids, "sess-bbb"],
    total_open: initial.total_open,
  });

  let dashboardCalls = 0;
  await page.route("**/api/dashboard*", async (route) => {
    dashboardCalls++;
    await route.fulfill({
      json: dashboardCalls === 1 ? initial : withExtra,
      headers: { "Cache-Control": "no-store" },
    });
  });

  api.events = 'data: {"type":"indexed","sids":["sess-bbb"]}\n\n';

  await gotoDashboard(page);

  await expect(
    page.locator("article.session", { hasText: "Just appeared" }),
  ).toBeVisible({ timeout: 10_000 });

  expect(dashboardCalls).toBeGreaterThanOrEqual(2);
});

test("SSE keepalive comments do not trigger refetches", async ({
  page,
  api,
}) => {
  api.events = ": keepalive\n\n";
  await gotoDashboard(page);

  await page.waitForTimeout(500);
  expect(api.dashboardRequests).toBe(1);
});
