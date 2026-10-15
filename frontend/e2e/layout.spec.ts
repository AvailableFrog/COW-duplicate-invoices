// Ticket #18: layout at 1440 and 1024 CSS pixels, with screenshots for a person to review.
//
// Every run checks that nothing is pushed off the side of the page: panels
// stack instead, and only evidence tables scroll, inside their own scroll box.
// Screenshots are written to docs/screenshots only when LTA_SCREENSHOTS=1, so
// an ordinary or CI run never rewrites the committed images.
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import type { Page } from "@playwright/test";

import { REPO_ROOT, expect, test } from "./app";

const PETER = "Possible duplicate L225526+L225761";
const WIDTHS = [1440, 1024];
const SHOTS = process.env.LTA_SCREENSHOTS === "1" ? join(REPO_ROOT, "docs", "screenshots") : null;

async function shoot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled" });
}

/** Elements that stick out past the right edge of the viewport, outside any scroll box. */
async function overflowing(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const out: string[] = [];
    for (const element of Array.from(document.querySelectorAll("body *"))) {
      if (element.closest(".table-scroll")) continue;
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      if (box.right > width + 1) out.push(`${element.tagName.toLowerCase()}.${element.className} right=${Math.round(box.right)} "${(element.textContent ?? "").trim().slice(0, 50)}" in ${element.parentElement?.tagName.toLowerCase()}.${element.parentElement?.className}`);
    }
    return out.slice(0, 10);
  });
}

async function pageScrollsSideways(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

for (const width of WIDTHS) {
  test.describe(`at ${width} CSS pixels`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("the Overview stacks its panels and never scrolls sideways", async ({ page, app }) => {
      await page.goto(app.baseURL);
      await expect(page.getByRole("button", { name: PETER })).toBeVisible();
      await expect(page.locator('[role="graphics-document"]').first()).toBeVisible();

      expect(await pageScrollsSideways(page)).toBe(false);
      expect(await overflowing(page)).toEqual([]);
      await shoot(page, `overview-${width}`);
    });

    test("claimed hours by job fits the page and its table scrolls inside its box", async ({ page, app }) => {
      await page.goto(app.baseURL);
      const panel = page.getByRole("region", { name: "Claimed hours by job (Approved, Job Number not 0)" });
      await expect(panel.locator('[role="graphics-document"]')).toHaveCount(1);
      await panel.getByText("View data", { exact: true }).click();
      await expect(panel.getByRole("table")).toBeVisible();

      expect(await pageScrollsSideways(page)).toBe(false);
      expect(await overflowing(page)).toEqual([]);
      await panel.evaluate((element) => element.scrollIntoView({ block: "start" }));
      await shoot(page, `claimed-hours-${width}`);
    });

    test("the evidence drawer's source comparison scrolls inside its box rather than clipping", async ({ page, app }) => {
      await page.goto(app.baseURL);
      await page.getByRole("button", { name: PETER }).click();
      const drawer = page.getByRole("dialog", { name: PETER });
      const source = drawer.getByRole("region", { name: "Source comparison, scrollable" });
      await source.scrollIntoViewIfNeeded();
      await expect(source.getByRole("rowheader")).toHaveCount(22);

      const fits = await source.evaluate((box) => {
        const table = box.querySelector("table") as HTMLTableElement;
        return {
          scrolls: getComputedStyle(box).overflowX === "auto",
          // The whole table is reachable: either it fits, or the box scrolls to its full width.
          reachable: box.scrollWidth >= table.getBoundingClientRect().width - 1,
        };
      });
      expect(fits).toEqual({ scrolls: true, reachable: true });
      expect(await overflowing(page)).toEqual([]);
      await shoot(page, `source-comparison-${width}`);
    });

    test("the Explore tab shows its chips and chart without sideways scrolling", async ({ page, app }) => {
      await page.goto(app.baseURL);
      await page.getByRole("tab", { name: "Explore" }).click();
      const explore = page.getByRole("region", { name: "Explore" });
      await explore.getByRole("radio", { name: /Start with all data/ }).check();
      await expect(explore.getByRole("region", { name: "Source records by Approval Status" })).toContainText("2,836 tickets");
      await expect(explore.locator('[role="graphics-document"]')).toHaveCount(1);

      expect(await pageScrollsSideways(page)).toBe(false);
      expect(await overflowing(page)).toEqual([]);
      // Show the chips and the chart they drew, not only the tab's introduction.
      await explore.getByRole("form", { name: "Chart chips" }).evaluate((form) => form.scrollIntoView({ block: "start" }));
      await shoot(page, `explore-${width}`);
    });
  });
}
