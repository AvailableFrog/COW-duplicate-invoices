import { boot, COMMITTED_WORKBOOK, expect, tabTo, test } from "./app";

const BANNED = ["paid", "saved", "lost", "liability"];

test("the value context is collapsed below the other views and opens by keyboard to three BBD figures", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const panel = page.getByRole("region", { name: "Value context" });
  await expect(panel).toBeVisible();
  // Collapsed by default: money is never the headline.
  await expect(panel.getByText("BBD 341,477.32")).toBeHidden();

  // It sits below the Overview's other views.
  const queue = page.getByRole("region", { name: "Processing queue" });
  const queueBox = await queue.boundingBox();
  const panelBox = await panel.boundingBox();
  expect(queueBox && panelBox && panelBox.y > queueBox.y + queueBox.height - 1).toBeTruthy();

  const disclosure = panel.locator(":scope > details > summary");
  await tabTo(page, disclosure, 300);
  await page.keyboard.press("Enter");

  const known = panel.getByRole("article", { name: "Known base-value components", exact: true });
  const flagged = panel.getByRole("article", { name: "Base value of flagged duplicates" });
  const extra = panel.getByRole("article", { name: "One extra claim per exact repeat, not flagged (hypothetical)" });
  await expect(known).toContainText("BBD 341,477.32");
  await expect(flagged).toContainText("BBD 3,399.71");
  await expect(extra).toContainText("BBD 571.37");
  for (const figure of [known, flagged, extra]) {
    await expect(figure).toContainText("Formula");
    await expect(figure).toContainText("Interpretation");
    await expect(figure).toContainText("Completeness");
  }
  await expect(panel).toContainText("881 hours across 122 Pending tickets that lack a usable Rate or hour value");
  await expect(known).toContainText("122 Pending tickets claim 881 hours");
  const groups = panel.getByRole("region", { name: "Behind the hypothetical figure: each exact repeat, not flagged" });
  await expect(groups.getByRole("row")).toHaveCount(5);
  await expect(groups.getByRole("row").filter({ hasText: "Peter Holder" })).toContainText("Example C");
  await expect(groups.getByRole("row").filter({ hasText: "Peter Holder" })).toContainText("620, 855");
  await expect(panel).toContainText("never added together");
  await expect(panel).toContainText("No analyst-reviewed alternative");

  // No label, or any other text on the panel, says paid, saved, lost or liability.
  const text = (await panel.innerText()).toLowerCase();
  expect(BANNED.filter((word) => text.includes(word))).toEqual([]);

  // Collapsing it again hides the figures.
  await disclosure.press("Enter");
  await expect(known).toBeHidden();
});

test("a kept/replaced link makes a labelled analyst-reviewed alternative appear; an outcome alone does not", async ({ page }) => {
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    const base = `${app.baseURL}/api/snapshots/${app.fingerprint}`;
    const outcome = await page.request.put(`${base}/pairs/620/855/outcome`, {
      data: { outcome: "needs_follow_up", note: "Ask Oliver", reviewer: "E2E reviewer" },
    });
    expect(outcome.ok()).toBeTruthy();
    await page.goto(app.baseURL);
    const panel = page.getByRole("region", { name: "Value context" });
    await panel.locator(":scope > details > summary").click();
    await expect(panel.getByRole("article", { name: "Known base-value components", exact: true })).toContainText("BBD 341,477.32");
    await expect(panel).toContainText("No analyst-reviewed alternative");

    const link = await page.request.put(`${base}/replacement-links/855/620`, {
      data: { reviewer: "E2E reviewer", rationale: "" },
    });
    expect(link.ok()).toBeTruthy();
    await page.reload();
    await panel.locator(":scope > details > summary").click();
    const reviewed = panel.getByRole("article", { name: "Analyst-reviewed known base-value components" });
    await expect(reviewed).toContainText("Analyst-reviewed alternative");
    await expect(reviewed).toContainText("BBD 341,361.08");
    await expect(reviewed).toContainText("1 replaced ticket left out (Excel row 855)");
    // The recorded figure stays as it is beside the alternative.
    await expect(panel.getByRole("article", { name: "Known base-value components", exact: true })).toContainText("BBD 341,477.32");
    const text = (await panel.innerText()).toLowerCase();
    expect(BANNED.filter((word) => text.includes(word))).toEqual([]);
  } finally {
    await app.stop();
  }
});
