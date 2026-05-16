import { expect, gotoDashboard, shiftDays, test, TODAY } from "./fixtures";

test("`/` focuses the filter, Escape blurs and clears it", async ({ page }) => {
  await gotoDashboard(page);
  const filter = page.locator(".filter");

  await expect(filter).not.toBeFocused();

  await page.keyboard.press("/");
  await expect(filter).toBeFocused();
  await expect(filter).toHaveValue("");

  await filter.type("abc");
  await expect(filter).toHaveValue("abc");

  await page.keyboard.press("Escape");
  await expect(filter).toHaveValue("");
  await expect(filter).not.toBeFocused();
});

test("ArrowLeft / ArrowRight shift the date in the URL", async ({ page }) => {
  await gotoDashboard(page);

  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(new RegExp(`date=${shiftDays(TODAY, -1)}`));

  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(new RegExp(`date=${TODAY}`));
});

test("`t` navigates to / clearing all params", async ({ page }) => {
  await gotoDashboard(page, "?from=2026-01-01&to=2026-01-07");
  await expect(page).toHaveURL(/from=/);

  await page.keyboard.press("t");

  await expect(page).not.toHaveURL(/from=/);
  await expect(page).not.toHaveURL(/to=/);
});

test("arrows are ignored while typing in the filter", async ({ page }) => {
  await gotoDashboard(page);
  const filter = page.locator(".filter");

  await page.keyboard.press("/");
  await expect(filter).toBeFocused();

  const urlBefore = page.url();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowRight");
  expect(page.url()).toBe(urlBefore);
});
