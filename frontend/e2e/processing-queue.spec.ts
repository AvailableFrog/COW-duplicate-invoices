import { expect, tabTo, test } from "./app";

test("a processing-queue bucket opens by keyboard, lists its tickets and opens one in the drawer", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const queue = page.getByRole("region", { name: "Processing queue" });
  const pending = queue.getByRole("article", { name: "Pending submissions" });
  const approved = queue.getByRole("article", { name: "Approved, not Keyed submissions" });
  await expect(pending).toContainText("Age since submission");
  await expect(pending).toContainText("Created to the analytical as-of date, 2026-10-08");
  await expect(pending).toContainText("129 tickets");
  await expect(approved).toContainText("149 tickets");
  // The chart describes itself; its table alternative holds every bucket.
  await expect(pending.locator('[role="graphics-document"]')).toHaveAttribute(
    "aria-label",
    /129 tickets by age since submission.*30 days or more: 1\./,
  );

  // Keyboard: open View data, then a bucket's button, and focus lands on the listed tickets.
  const viewData = pending.getByText("View data", { exact: true });
  await tabTo(page, viewData);
  await page.keyboard.press("Enter");
  const bucket = pending.getByRole("button", { name: "Show the 2 Pending tickets aged 7–13 days" });
  await tabTo(page, bucket);
  await page.keyboard.press("Enter");
  const heading = queue.getByRole("heading", { name: "Pending submissions, 7–13 days since submission: 2 tickets" });
  await expect(heading).toBeFocused();
  const list = queue.getByRole("region", { name: /7–13 days since submission/ });
  await expect(list).toContainText("Exactly the 2 tickets in the bar");
  const tickets = list.getByRole("button", { name: /^Pending ticket / });
  await expect(tickets).toHaveCount(2);
  await expect(list.getByRole("row").filter({ hasText: "L225309" })).toContainText("11 days");
  await expect(pending.getByRole("row").filter({ hasText: "7–13 days" })).toContainText("listed below");

  // Each ticket opens on its own in the evidence drawer, and Escape returns to it.
  const h = list.getByRole("button", { name: "Pending ticket L225309" });
  await tabTo(page, h);
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Pending ticket L225309" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Excel row 1072");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(h).toBeFocused();
});

test("clicking a bar lists the bucket's tickets, matching its count", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const queue = page.getByRole("region", { name: "Processing queue" });
  const approved = queue.getByRole("article", { name: "Approved, not Keyed submissions" });
  const bars = approved.locator('.vega-chart path[aria-roledescription="bar"]');
  await expect(bars).toHaveCount(8);
  await bars.nth(4).click();
  await expect(
    queue.getByRole("heading", { name: "Approved, not Keyed submissions, 4–6 days since submission: 46 tickets" }),
  ).toBeVisible();
  await expect(queue.getByRole("button", { name: /^Approved, not Keyed ticket / })).toHaveCount(46);
  await queue.getByRole("button", { name: "Close list" }).click();
  await expect(queue.getByRole("button", { name: /^Approved, not Keyed ticket / })).toHaveCount(0);
});
