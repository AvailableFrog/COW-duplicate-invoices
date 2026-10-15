import { join } from "node:path";

import { boot, COMMITTED_WORKBOOK, expect, tabTo, test, writeWorkbook } from "./app";

const H = "Possible duplicate L225309+L225552";
const HS_CONFLICT = "Work-period conflict between rows 829 and 1072";
const F = "Possible duplicate L224030+L224175";

test("a reviewer confirms H's proposed Alias by keyboard, the rules run again, and rejecting it needs a reason", async ({ page }) => {
  // A fresh process and data directory, so the decision cannot leak into other specs.
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    await page.goto(app.baseURL);
    const opener = page.getByRole("button", { name: H });
    await tabTo(page, opener, 300);
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("dialog", { name: H });
    await expect(drawer).toBeVisible();
    const edges = drawer.locator(".candidates > li");
    await expect(edges).toHaveCount(1);
    await expect(edges.first()).toContainText("Name-space variant between rows 829 and 1072");

    const alias = drawer.getByRole("form", { name: "Proposed Alias: “Mario Collymore” and “Mariocollymore”" });
    await expect(alias).toContainText("Decision: Proposed (no decision yet; the two labels stay separate)");
    await expect(alias).toContainText("A shared email is never a reason");

    await tabTo(page, drawer.getByRole("textbox", { name: "Reviewer" }));
    await page.keyboard.type("Alex Reviewer");
    await tabTo(page, alias.getByRole("textbox", { name: "Reason for this decision (required)" }));
    await page.keyboard.type("Oliver confirmed one person");
    await page.keyboard.press("Tab");
    await expect(alias.getByRole("button", { name: "Confirm Alias" })).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(alias.getByRole("status")).toHaveText(
      `Saved: Confirmed. The matching rules ran again and added ${HS_CONFLICT}.`,
    );
    await expect(alias).toContainText("Decision: Confirmed by Alex Reviewer");
    await expect(edges).toHaveCount(2);
    await expect(edges.nth(1)).toContainText(HS_CONFLICT);
    await expect(edges.nth(1)).toContainText("under the confirmed Alias");
    const history = drawer.getByRole("table", { name: "Every saved change for these tickets, newest first" });
    await expect(history.getByRole("row")).toHaveCount(2);
    await expect(history.getByRole("row").nth(1)).toContainText("Alias for “mario collymore” and “mariocollymore”");
    await expect(history.getByRole("row").nth(1)).toContainText("ProposedConfirmedOliver confirmed one person");

    // Rejecting without a reason is refused and announced; nothing changes.
    await tabTo(page, alias.getByRole("button", { name: "Reject Alias" }));
    await page.keyboard.press("Enter");
    await expect(alias.getByRole("status")).toContainText("Not saved: give a reason");
    await expect(history.getByRole("row")).toHaveCount(2);

    await alias.getByRole("textbox", { name: "Reason for this decision (required)" }).fill("Payroll lists two people");
    await alias.getByRole("button", { name: "Reject Alias" }).click();
    await expect(alias.getByRole("status")).toHaveText(
      `Saved: Rejected. The matching rules ran again and removed ${HS_CONFLICT}.`,
    );
    await expect(edges).toHaveCount(1);
    await expect(history.getByRole("row")).toHaveCount(3);
    await expect(history.getByRole("row").nth(1)).toContainText("ConfirmedRejectedPayroll lists two people");

    // F, the same employee on 10 September, is a separate possible duplicate with no Alias to decide.
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await page.getByRole("button", { name: F }).click();
    const f = page.getByRole("dialog", { name: F });
    await expect(f.locator(".candidates > li").first()).toContainText("Strict repeat between rows 2206 and 2351");
    await expect(f.getByRole("form", { name: /^Proposed Alias/ })).toHaveCount(0);
  } finally {
    await app.stop();
  }
});

test("a confirmed Alias links overlapping tickets under both labels, and rejecting it there unlinks them", async ({ page }, testInfo) => {
  const workbook = writeWorkbook(join(testInfo.outputDir, "alias.xlsx"), [
    { number: 1, fields: { Employee: "Ann Smith" } },
    { number: 2, fields: { Employee: "AnnSmith" } },
    { number: 3, fields: { Employee: "Ann Smith", Date: "2026-09-29", Time: "7:30am-11:30am", "Regular Hours": 4 } },
    {
      number: 4,
      fields: { Employee: "AnnSmith", Date: "2026-09-29", "Job Number": 20105, Time: "10:30am-2:30pm", "Regular Hours": 4 },
    },
  ]);
  const app = await boot(workbook);
  try {
    await page.goto(app.baseURL);
    const widened = page.getByRole("button", { name: "Possible duplicate L000003+L000004" });
    await expect(page.getByRole("button", { name: "Possible duplicate L000001+L000002" })).toBeVisible();
    await expect(widened).toHaveCount(0);

    await page.getByRole("button", { name: "Possible duplicate L000001+L000002" }).click();
    const proposing = page.getByRole("dialog", { name: "Possible duplicate L000001+L000002" });
    await proposing.getByRole("textbox", { name: "Reviewer" }).fill("Sam");
    const alias = proposing.getByRole("form", { name: "Proposed Alias: “Ann Smith” and “AnnSmith”" });
    await alias.getByRole("textbox", { name: "Reason for this decision (required)" }).fill("Same person");
    await alias.getByRole("button", { name: "Confirm Alias" }).click();
    await expect(alias.getByRole("status")).toContainText(
      "added Work-period conflict between rows 2 and 3; Work-period conflict between rows 4 and 5",
    );
    await page.keyboard.press("Escape");

    // The list now holds the overlap found under the two labels; its drawer offers the same Alias.
    await widened.click();
    const drawer = page.getByRole("dialog", { name: "Possible duplicate L000003+L000004" });
    const edge = drawer.locator(".candidates > li");
    await expect(edge).toHaveCount(1);
    await expect(edge).toContainText("Work-period conflict between rows 4 and 5");
    await expect(edge).toContainText("on different jobs under the confirmed Alias");
    const same = drawer.getByRole("form", { name: "Proposed Alias: “Ann Smith” and “AnnSmith”" });
    await expect(same).toContainText("Decision: Confirmed by Sam");
    await same.getByRole("textbox", { name: "Reason for this decision (required)" }).fill("Two people after all");
    await same.getByRole("button", { name: "Reject Alias" }).click();
    await expect(drawer.getByText(/no longer link these tickets/)).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(widened).toHaveCount(0);
  } finally {
    await app.stop();
  }
});
