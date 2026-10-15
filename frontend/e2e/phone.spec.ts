// Ticket #38: the three usability tasks at phone width (390 CSS pixels).
import { expect, test } from "./app";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

const PETER = "Possible duplicate L225526+L225761";

test("at 390 px a reviewer investigates C: the drawer opens and its 22-field source comparison scrolls", async ({ page, app }) => {
  await page.goto(app.baseURL);
  await page.getByRole("button", { name: PETER }).click();
  const drawer = page.getByRole("dialog", { name: PETER });
  await expect(drawer).toContainText("Same claim submitted twice");
  const source = drawer.getByRole("region", { name: "Source comparison, scrollable" });
  await source.scrollIntoViewIfNeeded();
  await expect(source.getByRole("rowheader")).toHaveCount(22);
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toBeHidden();
});

test("at 390 px F and H open as separate possible duplicates on different dates", async ({ page, app }) => {
  await page.goto(app.baseURL);
  for (const [name, date] of [
    ["Possible duplicate L224030+L224175", "2026-09-10"],
    ["Possible duplicate L225309+L225552", "2026-09-23"],
  ] as const) {
    await page.getByRole("button", { name }).click();
    const drawer = page.getByRole("dialog", { name });
    await expect(drawer).toContainText(`Date ${date}`);
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(drawer).toBeHidden();
  }
});

test("at 390 px the pending-by-supervisor chart is built from the chips and regrouped", async ({ page, app }) => {
  await page.goto(app.baseURL);
  await page.getByRole("tab", { name: "Explore" }).click();
  const explore = page.getByRole("region", { name: "Explore" });
  await explore.getByRole("radio", { name: /Start with all data/ }).check();
  await explore.getByRole("button", { name: "Make a bar chart of pending tickets by supervisor" }).click();
  const bySupervisor = explore.getByRole("region", { name: "Source records by Supervisor" });
  await expect(bySupervisor).toContainText("129 tickets");
  await explore.getByRole("form", { name: "Chart chips" }).getByRole("combobox", { name: "Group by" }).selectOption("Occupation");
  await expect(explore.getByRole("region", { name: "Source records by Occupation" })).toContainText("129 tickets");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
});
