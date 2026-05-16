import { expect, gotoDashboard, test } from "./fixtures";

test("session open/closed state persists across reloads via localStorage", async ({
  page,
}) => {
  await gotoDashboard(page);
  const card = page.locator("#sid-sess-aaa");
  await expect(card).not.toHaveClass(/closed/);

  await card.locator(".session-summary").click();
  await expect(card).toHaveClass(/closed/);
  expect(await page.evaluate(() => localStorage.getItem("session:sess-aaa")))
    .toBe("0");

  await page.reload();
  await expect(page.locator("#sid-sess-aaa")).toHaveClass(/closed/);

  await page.locator("#sid-sess-aaa .session-summary").click();
  await expect(page.locator("#sid-sess-aaa")).not.toHaveClass(/closed/);
  expect(await page.evaluate(() => localStorage.getItem("session:sess-aaa")))
    .toBe("1");

  await page.reload();
  await expect(page.locator("#sid-sess-aaa")).not.toHaveClass(/closed/);
});
