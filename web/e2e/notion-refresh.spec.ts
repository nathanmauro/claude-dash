import { expect, gotoDashboard, makeTodos, test } from "./fixtures";

test("refresh button posts refresh-notion, toasts, and flips source pill", async ({
  page,
  api,
}) => {
  let todosCalls = 0;
  await page.route("**/api/todos", async (route) => {
    todosCalls++;
    await route.fulfill({
      json:
        todosCalls === 1
          ? makeTodos({ source: "cache" })
          : makeTodos({ source: "live" }),
      headers: { "Cache-Control": "no-store" },
    });
  });

  await gotoDashboard(page);

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.locator(".src.stale")).toContainText("cached");

  const [refreshReq] = await Promise.all([
    page.waitForRequest((r) =>
      r.url().endsWith("/api/refresh-notion") && r.method() === "POST",
    ),
    sidebar.getByRole("button", { name: "refresh" }).click(),
  ]);
  expect(refreshReq.method()).toBe("POST");

  await expect(page.locator(".toast.ok")).toHaveText(/Notion todos refreshed/);
  await expect(sidebar.locator(".src.ok")).toHaveText("live");
  expect(api.refreshNotionCount).toBe(1);
  expect(todosCalls).toBeGreaterThanOrEqual(2);
});

test("refresh failure shows an error toast", async ({ page }) => {
  await page.route("**/api/refresh-notion", (route) =>
    route.fulfill({ json: { ok: false } }),
  );
  await gotoDashboard(page);

  await page.locator("aside.sidebar").getByRole("button", { name: "refresh" }).click();

  await expect(page.locator(".toast.err")).toHaveText(/refresh failed/i);
});
