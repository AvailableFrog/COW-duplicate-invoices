// Ticket #39: saved views.
import type { Page } from "@playwright/test";

import { COMMITTED_WORKBOOK, boot, expect, test, type RunningApp } from "./app";

async function openPanel(page: Page) {
  const panel = page.getByRole("region", { name: /^Saved views/ });
  const summary = panel.locator("summary");
  if ((await panel.locator("details").getAttribute("open")) === null) await summary.click();
  return panel;
}

async function withApp(run: (app: RunningApp) => Promise<void>) {
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    await run(app);
  } finally {
    await app.stop();
  }
}

test("Overview filters saved under a name come back when the view is opened", async ({ page }) => {
  await withApp(async (app) => {
    await page.goto(app.baseURL);
    const filters = page.getByRole("form", { name: "Filters" });
    await filters.getByRole("combobox", { name: "Status" }).selectOption("Pending");
    const panel = await openPanel(page);
    await panel.getByRole("textbox", { name: "Name" }).fill("Pending only");
    await panel.getByRole("button", { name: "Save the Overview filters" }).click();
    await expect(panel.getByRole("status")).toHaveText('Saved the Overview filters as "Pending only".');

    await filters.getByRole("button", { name: "Clear" }).click();
    await expect(filters.getByRole("combobox", { name: "Status" })).toHaveValue("");
    await panel.getByRole("button", { name: "Open Pending only" }).click();
    await expect(filters.getByRole("combobox", { name: "Status" })).toHaveValue("Pending");
    await expect(panel.getByRole("listitem").filter({ hasText: "Pending only" })).toContainText("current");
  });
});

test("an Explore chart saved as a view reopens with its plan after the chips change", async ({ page }) => {
  await withApp(async (app) => {
    await page.goto(app.baseURL);
    await page.getByRole("tab", { name: "Explore" }).click();
    const explore = page.getByRole("region", { name: "Explore" });
    await explore.getByRole("radio", { name: /Start with all data/ }).check();
    await explore.getByRole("button", { name: "Make a bar chart of pending tickets by supervisor" }).click();
    await expect(explore.getByRole("region", { name: "Source records by Supervisor" })).toContainText("129 tickets");

    const panel = await openPanel(page);
    await panel.getByRole("textbox", { name: "Name" }).fill("Pending by supervisor");
    await panel.getByRole("button", { name: "Save the Explore chart" }).click();
    await expect(panel.getByRole("status")).toContainText("Saved the Explore chart");

    await explore.getByRole("form", { name: "Chart chips" }).getByRole("combobox", { name: "Group by" }).selectOption("Occupation");
    await expect(explore.getByRole("region", { name: "Source records by Occupation" })).toBeVisible();
    await panel.getByRole("button", { name: "Open Pending by supervisor" }).click();
    await expect(explore.getByRole("region", { name: "Source records by Supervisor" })).toContainText("129 tickets");
  });
});

test("a view saved under another as-of date says what changed and opens only when asked", async ({ page }) => {
  await withApp(async (app) => {
    await page.goto(app.baseURL);
    const panel = await openPanel(page);
    await panel.getByRole("textbox", { name: "Name" }).fill("Everything");
    await panel.getByRole("button", { name: "Save the Overview filters" }).click();
    await expect(panel.getByRole("status")).toContainText("Saved");

    const moved = await fetch(`${app.baseURL}/api/as-of`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: "2026-10-20" }),
    });
    expect(moved.status).toBe(200);
    await page.reload();
    const reopened = await openPanel(page);
    const item = reopened.getByRole("listitem").filter({ hasText: "Everything" });
    await expect(item).toContainText("changed since saved");
    await item.getByRole("button", { name: "Open Everything" }).click();
    const warning = item.getByRole("alert");
    await expect(warning).toContainText("Saved with the as-of date 2026-10-08; it is now 2026-10-20");
    await warning.getByRole("button", { name: "Open anyway" }).click();
    await expect(reopened.getByRole("status")).toHaveText('Opened "Everything".');
  });
});

test("a view can be renamed and deleted, and deleting asks first", async ({ page }) => {
  await withApp(async (app) => {
    await page.goto(app.baseURL);
    const panel = await openPanel(page);
    await panel.getByRole("textbox", { name: "Name" }).fill("Draft");
    await panel.getByRole("button", { name: "Save the Overview filters" }).click();
    const item = panel.getByRole("listitem").filter({ hasText: "Draft" });
    await item.getByRole("button", { name: "Rename" }).click();
    await item.getByRole("textbox", { name: "New name" }).fill("Final");
    await item.getByRole("button", { name: "Save name" }).click();
    await expect(panel.getByRole("status")).toHaveText('Renamed to "Final".');

    const renamed = panel.getByRole("listitem").filter({ hasText: "Final" });
    await renamed.getByRole("button", { name: "Delete" }).click();
    await expect(renamed.getByRole("alert")).toContainText('Delete "Final"?');
    await renamed.getByRole("button", { name: "Delete it" }).click();
    await expect(panel.getByRole("status")).toHaveText('Deleted "Final".');
    await expect(panel).toContainText("No saved views yet.");
  });
});
