import { expect, gotoDashboard, test } from "./fixtures";

test("Resume submits {sid, cwd, prompt}, toasts, and invalidates dashboard", async ({
  page,
  api,
}) => {
  await gotoDashboard(page);
  const requestsBefore = api.dashboardRequests;

  const card = page.locator("article.session", { hasText: "Migration to FastAPI" });
  await expect(card).toBeVisible();
  await expect(card).not.toHaveClass(/closed/);

  await card.getByPlaceholder(/optional direction/i).fill("retry the failing test");

  const [request] = await Promise.all([
    page.waitForRequest((req) =>
      req.url().includes("/api/resume") && req.method() === "POST",
    ),
    card.getByRole("button", { name: /Resume/ }).click(),
  ]);

  expect(request.postDataJSON()).toEqual({
    sid: "sess-aaa",
    cwd: "/Users/test/proj/example",
    prompt: "retry the failing test",
  });

  await expect(page.locator(".toast.ok")).toHaveText(/launched in Terminal/i);
  await expect.poll(() => api.dashboardRequests).toBeGreaterThan(requestsBefore);
  expect(api.resumeBodies).toHaveLength(1);
});

test("Resume failure shows an error toast", async ({ page }) => {
  await page.route(/\/api\/resume(\?|$)/, (route) =>
    route.fulfill({ json: { ok: false, message: "no terminal" } }),
  );
  await gotoDashboard(page);

  const card = page.locator("article.session").first();
  await card.getByRole("button", { name: /Resume/ }).click();

  await expect(page.locator(".toast.err")).toHaveText(/resume failed/i);
});
