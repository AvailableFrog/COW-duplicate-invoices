import { readFileSync } from "node:fs";
import { join } from "node:path";

import { boot, expect, tabTo, test, writeWorkbook } from "./app";
import type { Page } from "@playwright/test";

async function startExplore(page: Page, baseURL: string) {
  await page.goto(baseURL);
  await page.getByRole("tab", { name: "Explore" }).click();
  const explore = page.getByRole("region", { name: "Explore" });
  await explore.getByRole("radio", { name: /Start with all data/ }).check();
  return explore;
}

test("a bar's source rows open by keyboard from the table and reproduce the bar", async ({ page, app }) => {
  const explore = await startExplore(page, app.baseURL);
  await explore.getByRole("button", { name: "Make a bar chart of pending tickets by supervisor" }).click();
  const result = explore.getByRole("region", { name: "Source records by Supervisor" });
  await expect(result).toContainText("129 tickets");

  await tabTo(page, result.getByText("View data", { exact: true }));
  await page.keyboard.press("Enter");
  await tabTo(page, result.getByRole("button", { name: "Show the 33 source rows for Bradford Goodluck" }));
  await page.keyboard.press("Enter");

  const rows = explore.getByRole("region", { name: "Source rows: Bradford Goodluck" });
  await expect(rows).toContainText("33 tickets, reproducing the chart's 33.");
  await expect(rows).toContainText(`Snapshot ${app.fingerprint.slice(0, 12)}`);
  await expect(rows.getByRole("heading", { name: "Source rows: Bradford Goodluck" })).toBeFocused();
  const table = rows.getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(34);
  await expect(table.getByRole("row").nth(1)).toContainText("Pending");

  // The Other bar lists exactly the tickets it combines.
  await result.getByRole("button", { name: /source rows for Other \(13 supervisors\)/ }).click();
  await expect(explore.getByRole("region", { name: "Source rows: Other (13 supervisors)" })).toContainText(
    "24 tickets, reproducing the chart's 24.",
  );
});

test("How this was calculated is collapsed until opened and shows formula, exclusions, source rows and plan", async ({ page, app }) => {
  const explore = await startExplore(page, app.baseURL);
  await explore.getByRole("button", { name: /ten busiest jobs/ }).click();
  const result = explore.getByRole("region", { name: "Claimed hours by Job Number" });
  const panel = result.locator("details.how-calculated");
  await expect(panel).not.toHaveAttribute("open", "");
  await expect(panel.getByText("Formula")).toBeHidden();

  await tabTo(page, panel.getByText("How this was calculated", { exact: true }));
  await page.keyboard.press("Enter");
  await expect(panel).toHaveAttribute("open", "");
  await expect(panel).toContainText("Regular Hours + Overtime + Double Time");
  await expect(panel).toContainText("Exclusions");
  await expect(panel).toContainText(/Source rows\s*[\d,]+ tickets: Excel rows/);
  await expect(panel).toContainText("10 bars, largest first; the other");
  await expect(panel.locator("pre")).toContainText('"metric_id": "claimed_hours"');
  await expect(panel.locator("pre")).toContainText('"include_other": true');

  await panel.getByRole("button", { name: "Inspect source rows" }).click();
  await expect(explore.getByRole("region", { name: "Source rows: Every ticket in the chart" })).toContainText(
    /tickets, [\d,.]+ hours in all, reproducing the chart's [\d,.]+\./,
  );
});

test("weekly Created counts draw as a line in date order, and Last 30 days shows its absolute range", async ({ page, app }) => {
  const explore = await startExplore(page, app.baseURL);
  const chips = explore.getByRole("form", { name: "Chart chips" });
  await tabTo(page, chips.getByRole("combobox", { name: "Group by" }));
  await page.keyboard.type("Week");
  await tabTo(page, chips.getByRole("combobox", { name: "Chart" }));
  await page.keyboard.type("Line");
  await expect(chips.getByRole("combobox", { name: "Chart" })).toHaveValue("line");
  // A line is offered only for ordered dates.
  await chips.getByRole("combobox", { name: "Group by" }).selectOption("Supervisor");
  await expect(chips.getByRole("combobox", { name: "Chart" })).not.toHaveValue("line");
  await expect(chips.getByRole("combobox", { name: "Chart" }).locator("option[value=line]")).toHaveAttribute("disabled", "");
  await chips.getByRole("combobox", { name: "Group by" }).selectOption("Week");
  await chips.getByRole("combobox", { name: "Chart" }).selectOption("line");

  const result = explore.getByRole("region", { name: "Source records by week of Created" });
  await expect(result.locator('[role="graphics-document"]')).toHaveAttribute(
    "aria-label",
    /line over time of 2,836 tickets\. Week of 31 Aug 2026: 1; Week of 7 Sep 2026: 520; Week of 14 Sep 2026: 604; Week of 21 Sep 2026: 672; Week of 28 Sep 2026: 674; Week of 5 Oct 2026: 365\./,
  );
  await expect(result).toContainText("A week runs Monday to Sunday");

  await chips.getByRole("combobox", { name: "Range" }).selectOption("last_30_days");
  await expect(result).toContainText("Last 30 days: Created from 2026-09-09 to 2026-10-08, resolved against the as-of date 2026-10-08");
  await expect(result.locator('[role="graphics-document"]')).toHaveAttribute("aria-label", /Week of 7 Sep 2026: \d+;/);
});

test("CSV downloads protect formula-like cells, the screen shows them raw, and an empty plan shows no zeros", async ({ page }, testInfo) => {
  const workbook = writeWorkbook(join(testInfo.outputDir, "formula.xlsx"), [
    { number: 1, fields: { "Description of Job Work": { literal: "=HYPERLINK(\"http://example.invalid\",\"x\")" }, Supervisor: "Supervisor A" } },
    { number: 2, fields: { "Description of Job Work": "+cmd", Supervisor: { literal: "=1+1" } } },
  ]);
  const app = await boot(workbook);
  try {
    const explore = await startExplore(page, app.baseURL);
    const chips = explore.getByRole("form", { name: "Chart chips" });
    await chips.getByRole("combobox", { name: "Group by" }).selectOption("Supervisor");
    const result = explore.getByRole("region", { name: "Source records by Supervisor" });
    await expect(result).toContainText("2 tickets");

    await result.getByRole("button", { name: "Inspect source rows" }).click();
    const rows = explore.getByRole("region", { name: "Source rows: Every ticket in the chart" });
    await expect(rows.getByRole("cell", { name: '=HYPERLINK("http://example.invalid","x")' })).toBeVisible();
    await expect(rows.getByRole("cell", { name: "=1+1" })).toBeVisible();

    const drillDownload = page.waitForEvent("download");
    await rows.getByRole("button", { name: "Download these rows (CSV)" }).click();
    const drilled = await drillDownload;
    expect(drilled.suggestedFilename()).toMatch(/^explore-source-rows-[0-9a-f]{12}-as-of-2026-10-08\.csv$/);
    const drillText = readFileSync(await drilled.path(), "utf-8");
    expect(drillText).toContain('"\'=HYPERLINK(""http://example.invalid"",""x"")"');
    expect(drillText).toContain('"\'+cmd"');
    expect(drillText).toContain('"\'=1+1"');
    expect(drillText).not.toMatch(/(^|,)"=/m);

    const tableDownload = page.waitForEvent("download");
    await result.getByRole("button", { name: "Download the table (CSV)" }).click();
    const tableText = readFileSync(await (await tableDownload).path(), "utf-8");
    expect(tableText).toContain('"\'=1+1"');
    expect(tableText).toContain('"Total","2"');

    // Nothing was created in September, so the previous month is empty: an empty state, never a zero.
    await chips.getByRole("combobox", { name: "Range" }).selectOption("previous_month");
    await expect(result.getByRole("status").filter({ hasText: "Nothing to show." })).toContainText("an empty result is not a zero");
    await expect(result.locator('[role="graphics-document"]')).toHaveCount(0);
    await expect(result).not.toContainText("0 tickets");
  } finally {
    await app.stop();
  }
});
