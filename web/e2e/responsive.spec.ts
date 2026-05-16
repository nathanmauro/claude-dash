import { expect, gotoDashboard, test } from "./fixtures";

test("at narrow viewport sidebar stacks above content", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 });
  await gotoDashboard(page);

  const sidebar = await page.locator("aside.sidebar").boundingBox();
  const content = await page.locator("section.content").boundingBox();
  expect(sidebar).not.toBeNull();
  expect(content).not.toBeNull();
  expect(sidebar!.y + sidebar!.height).toBeLessThanOrEqual(content!.y + 1);
});

test("at wide viewport sidebar sits beside content", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await gotoDashboard(page);

  const sidebar = await page.locator("aside.sidebar").boundingBox();
  const content = await page.locator("section.content").boundingBox();
  expect(sidebar!.x + sidebar!.width).toBeLessThanOrEqual(content!.x + 1);
  expect(Math.abs(sidebar!.y - content!.y)).toBeLessThan(2);
});
