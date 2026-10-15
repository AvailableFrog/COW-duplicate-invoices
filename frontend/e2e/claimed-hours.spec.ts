// Ticket #33: claimed hours by job on the Overview.
import { COMMITTED_WORKBOOK, boot, expect, tabTo, test } from "./app";

const TITLE = "Claimed hours by job (Approved, Job Number not 0)";

test("claimed hours by job states its scope, switches to tickets and drills into a job by keyboard", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const panel = page.getByRole("region", { name: TITLE });
  await expect(panel).toContainText("including possible repeats");
  const chart = panel.locator('[role="graphics-document"]');
  await expect(chart).toHaveAttribute("aria-label", /40972 Shop hill: 2,536/);
  await expect(chart).toHaveAttribute("aria-label", /Other \(76 jobs\)/);

  // The table alternative and a job's source rows, by keyboard, starting from the panel's heading as a
  // keyboard user arrives by heading navigation, past the long Review priorities list.
  await panel.getByRole("heading", { name: TITLE }).focus();
  await tabTo(page, panel.getByText("View data", { exact: true }));
  await page.keyboard.press("Enter");
  const shopHill = panel.getByRole("row").filter({ hasText: "40972 Shop hill" });
  await expect(shopHill).toContainText("2,536");
  await tabTo(page, shopHill.getByRole("button"));
  await page.keyboard.press("Enter");
  const rows = panel.getByRole("region", { name: /^Source rows:/ });
  await expect(rows).toContainText("40972");
  await expect(rows.getByRole("status").filter({ hasText: "reproducing the chart's 2,536" })).toBeVisible();

  // The same panel counted in tickets instead of hours; the measure sits above the chart, so start from the heading.
  await panel.getByRole("heading", { name: TITLE }).focus();
  // Tab reaches the checked radio; the arrow key moves to, and selects, the next measure.
  await tabTo(page, panel.getByRole("radio", { name: "Claimed hours" }));
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("region", { name: "Tickets by job (Approved, Job Number not 0)" })).toContainText("2,583");
});

test("a kept/replaced link adds a labelled analyst-reviewed alternative beside the recorded hours", async ({ page }) => {
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    await page.goto(app.baseURL);
    const panel = page.getByRole("region", { name: TITLE });
    await expect(panel.locator('[role="graphics-document"]')).toHaveCount(1);
    await expect(panel).not.toContainText("Analyst-reviewed alternative");

    const linked = await fetch(`${app.baseURL}/api/snapshots/${app.fingerprint}/replacement-links/620/855`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer: "Analyst", rationale: "620 repeats 855" }),
    });
    expect(linked.status).toBe(200);
    await page.reload();

    await expect(panel).toContainText("Analyst-reviewed alternative: replaced tickets left out");
    await expect(panel).toContainText("1 ticket linked as replaced");
    await expect(panel.locator('[role="graphics-document"]')).toHaveCount(2);
    const reviewed = panel.getByRole("region", { name: /^Analyst-reviewed claimed hours/ });
    await expect(reviewed).toContainText("17,658");
  } finally {
    await app.stop();
  }
});
