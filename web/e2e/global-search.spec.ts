import {
  expect,
  gotoDashboard,
  makeSearchHits,
  test,
} from "./fixtures";

test("typing in filter debounces and calls /api/search once", async ({
  page,
  api,
}) => {
  api.search = makeSearchHits();
  await gotoDashboard(page);

  await page.locator(".filter").fill("migration");

  await expect.poll(() => api.searchRequests.length, { timeout: 2_000 })
    .toBeGreaterThanOrEqual(1);
  expect(api.searchRequests).toContain("migration");
});

test("search results render with bold-highlighted snippets", async ({
  page,
  api,
}) => {
  api.search = makeSearchHits();
  await gotoDashboard(page);
  await page.locator(".filter").fill("migration");

  const results = page.locator(".search-results");
  await expect(results).toBeVisible();
  await expect(results.locator(".search-hit")).toHaveCount(2);
  await expect(results.locator(".hit-snippet b").first()).toHaveText("migration");
});

test("queries shorter than 3 chars do not hit /api/search", async ({
  page,
  api,
}) => {
  api.search = makeSearchHits();
  await gotoDashboard(page);

  await page.locator(".filter").fill("mi");
  await page.waitForTimeout(400);

  expect(api.searchRequests).toHaveLength(0);
  await expect(page.locator(".search-results")).toHaveCount(0);
});

test("ArrowDown moves active highlight; Enter expands the target session", async ({
  page,
  api,
}) => {
  api.search = makeSearchHits();
  await page.addInitScript(() => {
    window.localStorage.setItem("session:sess-aaa", "0");
  });
  await gotoDashboard(page);

  const card = page.locator("#sid-sess-aaa");
  await expect(card).toHaveClass(/closed/);

  await page.locator(".filter").fill("migration");
  const hits = page.locator(".search-hit");
  await expect(hits).toHaveCount(2);
  await expect(hits.nth(0)).toHaveClass(/active/);

  await page.locator(".filter").press("ArrowDown");
  await expect(hits.nth(1)).toHaveClass(/active/);

  await page.locator(".filter").press("ArrowUp");
  await expect(hits.nth(0)).toHaveClass(/active/);

  await page.locator(".filter").press("Enter");
  await expect(card).not.toHaveClass(/closed/);
});
