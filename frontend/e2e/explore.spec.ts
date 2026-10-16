import { join } from "node:path";

import { boot, expect, tabTo, test, writeWorkbook } from "./app";

test("the third usability task: pending-by-supervisor bars built from the chips, then regrouped, by keyboard", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const tab = page.getByRole("tab", { name: "Explore" });
  await tabTo(page, tab);
  await page.keyboard.press("Enter");
  const explore = page.getByRole("region", { name: "Explore" });
  await expect(explore).toContainText("Ask in words, or build a chart from the chips below.");
  await expect(explore.getByRole("textbox")).toHaveCount(0);

  // The starting choice comes first and stays visible; nothing runs until it is made.
  await expect(explore.getByRole("status").first()).toHaveText(/Choose how to start/);
  await tabTo(page, explore.getByRole("radio", { name: /Use Overview filters/ }));
  await page.keyboard.press("ArrowDown");
  await expect(explore.getByRole("radio", { name: /Start with all data/ })).toBeChecked();
  await expect(explore).toContainText("Starting from all data. Only the chips below filter the chart.");
  // With no model configured there is no question field, only how to set one up.
  await expect(explore.getByRole("region", { name: "Ask the data" })).toContainText("No language model is configured");

  const starters = explore.getByRole("region", { name: "Starter questions" }).getByRole("button");
  await expect(starters).toHaveCount(6);
  await expect(starters.first()).toHaveAttribute("aria-pressed", "true");
  const result = explore.getByRole("region", { name: "Source records by Approval Status" });
  await expect(result).toContainText("2,836 tickets");

  // Filter to Pending, group by Supervisor and draw horizontal bars, all from the chips.
  const chips = explore.getByRole("form", { name: "Chart chips" });
  await tabTo(page, chips.getByRole("button", { name: "Add a filter" }));
  await page.keyboard.press("Enter");
  const filter = chips.getByRole("group", { name: "Filter 1" });
  await tabTo(page, filter.getByRole("combobox", { name: "Filter 1 value" }));
  await page.keyboard.type("Pending");
  await expect(filter.getByRole("combobox", { name: "Filter 1 value" })).toHaveValue("Pending");
  await tabTo(page, chips.getByRole("combobox", { name: "Group by" }));
  await page.keyboard.type("Supervisor");
  await tabTo(page, chips.getByRole("combobox", { name: "Chart" }));
  await page.keyboard.type("Horizontal");

  const bySupervisor = explore.getByRole("region", { name: "Source records by Supervisor" });
  await expect(bySupervisor).toContainText("all dates; Approval Status is Pending");
  await expect(bySupervisor).toContainText("129 tickets");
  await expect(bySupervisor).toContainText("Grain Ticket");
  await expect(bySupervisor.locator('[role="graphics-document"]')).toHaveAttribute(
    "aria-label",
    /horizontal bars of 129 tickets\. Bradford Goodluck: 33; .*Other \(13 supervisors\): 24\./,
  );
  await expect(bySupervisor).toContainText("says nothing about supervisor performance");
  // The chips now match the starter question, which shows as chosen.
  await expect(explore.getByRole("button", { name: "Make a bar chart of pending tickets by supervisor" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // The table alternative, by keyboard, lists every supervisor including those combined as Other.
  await tabTo(page, bySupervisor.getByText("View data", { exact: true }));
  await page.keyboard.press("Enter");
  const table = bySupervisor.getByRole("table");
  await expect(table.getByRole("row").filter({ hasText: "Bradford Goodluck" })).toContainText("33Own bar");
  await expect(table.getByRole("cell", { name: "In Other", exact: true })).toHaveCount(13);
  await expect(table.getByRole("row").filter({ hasText: "Other (13 supervisors)" })).toContainText("24");
  await expect(table.getByRole("row").filter({ hasText: "Total" })).toContainText("129");

  // Change the grouping with the same chip.
  await tabTo(page, chips.getByRole("combobox", { name: "Group by" }));
  await page.keyboard.type("Occupation");
  const byOccupation = explore.getByRole("region", { name: "Source records by Occupation" });
  await expect(byOccupation).toContainText("all dates; Approval Status is Pending");
  await expect(byOccupation.locator('[role="graphics-document"]')).toHaveAttribute("aria-label", /of 129 tickets\./);
  await expect(bySupervisor).toHaveCount(0);
});

test("Overview filters are used only when chosen, and the choice stays visible", async ({ page, app }) => {
  await page.goto(app.baseURL);
  await page.getByRole("form", { name: "Filters" }).getByRole("combobox", { name: "Status" }).selectOption("Pending");
  await page.getByRole("tab", { name: "Explore" }).click();
  const explore = page.getByRole("region", { name: "Explore" });
  await expect(explore.getByRole("radio", { name: /Use Overview filters · now all dates; Approval Status Pending/ })).not.toBeChecked();

  await explore.getByRole("radio", { name: /Use Overview filters/ }).check();
  await expect(explore).toContainText("Starting from the Overview filters: all dates; Approval Status Pending.");
  const result = explore.getByRole("region", { name: "Source records by Approval Status" });
  await expect(result).toContainText("Starting filters Overview filters (all dates; Approval Status Pending)");
  await expect(result).toContainText("129 tickets");

  await explore.getByRole("radio", { name: /Start with all data/ }).check();
  await expect(result).toContainText("Starting filters All data");
  await expect(result).toContainText("2,836 tickets");
});

test("a new Snapshot withdraws the displayed chart until the plan is rerun", async ({ page }, testInfo) => {
  const path = join(testInfo.outputDir, "export.xlsx");
  writeWorkbook(path, [{ number: 1, fields: {} }, { number: 2, fields: { "Approval Status": "Pending" } }]);
  const app = await boot(path);
  try {
    await page.goto(app.baseURL);
    await page.getByRole("tab", { name: "Explore" }).click();
    const explore = page.getByRole("region", { name: "Explore" });
    await explore.getByRole("radio", { name: /Start with all data/ }).check();
    const result = explore.getByRole("region", { name: "Source records by Approval Status" });
    await expect(result).toContainText("2 tickets");
    await expect(result.locator('[role="graphics-document"]')).toHaveCount(1);

    writeWorkbook(path, [
      { number: 1, fields: {} },
      { number: 2, fields: { "Approval Status": "Pending" } },
      { number: 3, fields: { "Approval Status": "Pending" } },
    ]);
    await page.getByRole("button", { name: "Reimport" }).click();
    await expect(result.getByRole("alert")).toContainText("Its numbers are withdrawn until you run the plan again");
    await expect(result.locator('[role="graphics-document"]')).toHaveCount(0);
    await expect(result.getByRole("table")).toHaveCount(0);

    await result.getByRole("button", { name: "Rerun the plan" }).click();
    await expect(result).toContainText("3 tickets");
    await expect(result.getByRole("alert")).toHaveCount(0);
    await expect(result.locator('[role="graphics-document"]')).toHaveAttribute("aria-label", /Pending: 2/);
  } finally {
    await app.stop();
  }
});
