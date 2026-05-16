import { expect, gotoDashboard, shiftDays, test, TODAY } from "./fixtures";

test("clicking 7d sets the from/to URL params and refetches", async ({
  page,
  api,
}) => {
  await gotoDashboard(page);
  expect(api.dashboardRequests).toBe(1);

  await page.getByRole("button", { name: "7d" }).click();

  await expect(page).toHaveURL(
    new RegExp(`from=${shiftDays(TODAY, -6)}.*to=${TODAY}`),
  );
  await expect.poll(() => api.dashboardRequests).toBeGreaterThanOrEqual(2);
});

test("clicking 30d sets a 30-day range", async ({ page, api }) => {
  await gotoDashboard(page);
  await page.getByRole("button", { name: "30d" }).click();
  await expect(page).toHaveURL(
    new RegExp(`from=${shiftDays(TODAY, -29)}.*to=${TODAY}`),
  );
});

test("stepping back/forward shifts the range by one day", async ({
  page,
  api,
}) => {
  await gotoDashboard(page);

  await page.getByRole("button", { name: "7d" }).click();
  await expect(page).toHaveURL(/from=/);

  await page.getByTitle("shift 1 day earlier (←)").click();
  await expect(page).toHaveURL(
    new RegExp(`from=${shiftDays(TODAY, -7)}.*to=${shiftDays(TODAY, -1)}`),
  );

  await page.getByTitle("shift 1 day later (→)").click();
  await expect(page).toHaveURL(
    new RegExp(`from=${shiftDays(TODAY, -6)}.*to=${TODAY}`),
  );
});

test("Today clears the range params", async ({ page }) => {
  await gotoDashboard(page, "?from=2026-01-01&to=2026-01-07");
  await expect(page).toHaveURL(/from=2026-01-01/);

  await page.getByRole("button", { name: "Today" }).click();

  await expect(page).not.toHaveURL(/from=/);
  await expect(page).not.toHaveURL(/to=/);
});
