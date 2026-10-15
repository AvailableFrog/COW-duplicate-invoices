// Ticket #40: carrying review decisions forward to a new Snapshot.
import AxeBuilder from "@axe-core/playwright";
import { join } from "node:path";

import { boot, expect, test, writeWorkbook } from "./app";

const ANN = { Employee: "Ann Smith" };
const CY = { Employee: "Cy Dee" };

async function saveOutcome(baseURL: string, fingerprint: string, rows: [number, number], outcome: string) {
  const response = await fetch(`${baseURL}/api/snapshots/${fingerprint}/pairs/${rows[0]}/${rows[1]}/outcome`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome, note: "", reference: "", reviewer: "Sam", rationale: "" }),
  });
  expect(response.status).toBe(200);
}

test("after a reimport the earlier outcomes are proposed: unchanged ones carry in one step, changed ones after a check", async ({
  page,
}, testInfo) => {
  const path = join(testInfo.outputDir, "export.xlsx");
  writeWorkbook(path, [
    { number: 1, fields: ANN },
    { number: 2, fields: ANN },
    { number: 3, fields: CY },
    { number: 4, fields: CY },
  ]);
  const app = await boot(path);
  try {
    await saveOutcome(app.baseURL, app.fingerprint, [2, 3], "confirmed_duplicate");
    await saveOutcome(app.baseURL, app.fingerprint, [4, 5], "not_a_duplicate");
    await page.goto(app.baseURL);
    await expect(page.getByRole("heading", { name: /Earlier review decisions/ })).toHaveCount(0);

    // The new export puts another ticket first, so every row moves; ticket 4's Modified By changed.
    writeWorkbook(path, [
      { number: 9, fields: { Employee: "Bo Lee" } },
      { number: 1, fields: ANN },
      { number: 2, fields: ANN },
      { number: 3, fields: CY },
      { number: 4, fields: { ...CY, "Modified By": "Reviewer B" } },
    ]);
    await page.getByRole("button", { name: "Reimport" }).click();
    const panel = page.getByRole("region", { name: /Earlier review decisions/ });
    await expect(panel.getByRole("heading")).toHaveText("Earlier review decisions (2 to answer)");
    await panel.getByRole("textbox", { name: "Reviewer" }).fill("Alex");

    const unchanged = panel.getByRole("listitem", { name: /L000001 and L000002/ });
    await expect(unchanged).toContainText("Unchanged in this export");
    await expect(unchanged).toContainText("Saved by Sam");
    await unchanged.getByRole("button", { name: "Carry forward" }).click();
    await expect(panel.getByRole("status")).toHaveText("Carried forward: “Confirmed duplicate” on L000001 and L000002.");

    const changed = panel.getByRole("listitem", { name: /L000003 and L000004/ });
    await expect(changed).toContainText("Changed in this export");
    const differences = changed.getByRole("region", { name: /What changed/ });
    await expect(differences.getByRole("row", { name: /Modified By/ })).toContainText("Reviewer AReviewer B");
    const carry = changed.getByRole("button", { name: "Carry forward" });
    await expect(carry).toBeDisabled();
    await changed.getByRole("checkbox", { name: /I have checked what changed/ }).check();
    await changed.getByRole("textbox", { name: /Reason/ }).fill("Only the approver's name changed");
    const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).include(".carry-forward").analyze();
    expect(violations.map((v) => v.id)).toEqual([]);
    await carry.click();

    await expect(panel.getByRole("heading")).toHaveText("Earlier review decisions");
    await expect(panel).toContainText("Every earlier decision has been answered for this export.");
    await panel.getByText(/Already answered \(2\)/).click();
    await expect(panel.getByRole("list", { name: "Answered decisions" })).toContainText("carried after revalidating");

    // The carried outcome now shows in the evidence drawer of the new Snapshot, saved by its original reviewer.
    await page.getByRole("button", { name: "Possible duplicate L000001+L000002" }).click();
    const drawer = page.getByRole("dialog", { name: "Possible duplicate L000001+L000002" });
    await expect(drawer).toContainText("by Sam");
    await expect(drawer.getByRole("table").filter({ hasText: "Carried forward from Snapshot" })).toContainText("Alex");
  } finally {
    await app.stop();
  }
});

test("a decision can be declined and is not proposed again", async ({ page }, testInfo) => {
  const path = join(testInfo.outputDir, "export.xlsx");
  writeWorkbook(path, [
    { number: 1, fields: ANN },
    { number: 2, fields: ANN },
  ]);
  const app = await boot(path);
  try {
    await saveOutcome(app.baseURL, app.fingerprint, [2, 3], "needs_follow_up");
    writeWorkbook(path, [
      { number: 1, fields: ANN },
      { number: 2, fields: ANN },
      { number: 3, fields: {} },
    ]);
    await page.goto(app.baseURL);
    await page.getByRole("button", { name: "Reimport" }).click();
    const panel = page.getByRole("region", { name: /Earlier review decisions/ });
    await panel.getByRole("textbox", { name: "Reviewer" }).fill("Alex");
    await panel.getByRole("button", { name: "Don't carry" }).click();
    await expect(panel.getByRole("status")).toHaveText("Not carried: “Needs follow-up” on L000001 and L000002.");
    await page.reload();
    const reloaded = page.getByRole("region", { name: /Earlier review decisions/ });
    await expect(reloaded).toContainText("Every earlier decision has been answered for this export.");
  } finally {
    await app.stop();
  }
});
