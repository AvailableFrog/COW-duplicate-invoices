// Ticket #34: submission and review timing on the Overview.
import { expect, tabTo, test } from "./app";

test("weekly submissions stack by current status, name every colour, and a segment drills down by keyboard", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const panel = page.getByRole("region", { name: "Submission and review timing" });
  const weekly = panel.getByRole("region", { name: "Weekly submissions by current status" });
  await expect(weekly).toContainText("not a history of status changes");
  await expect(weekly.locator('[role="graphics-document"]')).toHaveAttribute(
    "aria-label",
    /2,836 tickets by submission week and current status\. .*Week of 7 Sep 2026: 493 Approved, 0 Pending, 27 Rejected/,
  );
  await expect(weekly.getByRole("list", { name: "Status colours" }).getByRole("listitem")).toHaveText(["Approved", "Pending", "Rejected"]);

  await panel.getByRole("heading", { name: "Submission and review timing" }).focus();
  await tabTo(page, weekly.getByText("View data", { exact: true }));
  await page.keyboard.press("Enter");
  const rejected = weekly.getByRole("button", { name: "List the 27 tickets submitted in the week of 7 sep 2026 and now Rejected" });
  await tabTo(page, rejected);
  await page.keyboard.press("Enter");
  const rows = weekly.getByRole("region", { name: /^Source rows:/ });
  await expect(rows.getByRole("status").filter({ hasText: "reproducing the chart's 27" })).toBeVisible();
  await expect(rows.getByRole("cell", { name: "Rejected", exact: true }).first()).toBeVisible();
});

test("the lag and approval-interval distributions disclose what they leave out", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const panel = page.getByRole("region", { name: "Submission and review timing" });
  await expect(panel.locator('[role="graphics-document"]')).toHaveCount(3);

  await expect(panel).toContainText("Negative lags and dates outside the reporting window are listed apart");
  await expect(panel).toContainText("Date as recorded falls after Created");
  await expect(panel).toContainText("Approved tickets only");
  await expect(panel).toContainText("Date Approved falls before Created");
});
