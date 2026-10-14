import { join } from "node:path";

import { boot, COMMITTED_WORKBOOK, expect, tabTo, test, writeWorkbook } from "./app";

const PETER = "Possible duplicate L225526+L225761";

test("a reviewer sets and then revises a Review Outcome by keyboard, and the history and list show it", async ({ page }) => {
  // A fresh process and data directory, so the saved outcome cannot leak into other specs.
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    await page.goto(app.baseURL);
    const opener = page.getByRole("button", { name: PETER });
    await tabTo(page, opener);
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("dialog", { name: PETER });
    await expect(drawer).toBeVisible();

    const pair = drawer.getByRole("form", { name: "L225761 (row 620) and L225526 (row 855)" });
    await expect(pair).toContainText("Saved outcome: Not reviewed");

    await tabTo(page, drawer.getByRole("textbox", { name: "Reviewer" }));
    await page.keyboard.type("Alex Reviewer");
    // The radio group takes one Tab stop; arrow keys move the choice.
    await tabTo(page, pair.getByRole("radio", { name: /^Not reviewed/ }));
    await page.keyboard.press("ArrowDown");
    await expect(pair.getByRole("radio", { name: /^Confirmed duplicate/ })).toBeChecked();
    await page.keyboard.press("Tab");
    await expect(pair.getByRole("textbox", { name: "Note" })).toBeFocused();
    await page.keyboard.type("Same claim, same day, same job");
    await page.keyboard.press("Tab");
    await page.keyboard.type("Email from Oliver, 9 October");
    await tabTo(page, pair.getByRole("button", { name: "Save outcome" }));
    await page.keyboard.press("Enter");

    await expect(pair.getByRole("status")).toHaveText("Saved: Confirmed duplicate.");
    await expect(pair).toContainText("Saved outcome: Confirmed duplicate by Alex Reviewer");
    const history = drawer.getByRole("table", { name: "Every saved change for these tickets, newest first" });
    await expect(history.getByRole("row")).toHaveCount(2);
    await expect(history.getByRole("row").nth(1)).toContainText("Alex Reviewer");
    await expect(history.getByRole("row").nth(1)).toContainText(
      "Not reviewedConfirmed duplicate; note: Same claim, same day, same job; reference: Email from Oliver, 9 October",
    );

    // Revising needs a reason; the refusal is announced and nothing changes.
    await tabTo(page, pair.getByRole("radio", { name: /^Confirmed duplicate/ }));
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(pair.getByRole("radio", { name: /^Needs follow-up/ })).toBeChecked();
    await tabTo(page, pair.getByRole("button", { name: "Save outcome" }));
    await page.keyboard.press("Enter");
    await expect(pair.getByRole("status")).toContainText("Not saved: give a reason");
    await expect(history.getByRole("row")).toHaveCount(2);

    await tabTo(page, pair.getByRole("textbox", { name: /^Reason for this change/ }));
    await page.keyboard.type("Oliver wants payroll checked first");
    await tabTo(page, pair.getByRole("button", { name: "Save outcome" }));
    await page.keyboard.press("Enter");
    await expect(pair.getByRole("status")).toHaveText("Saved: Needs follow-up.");
    await expect(history.getByRole("row")).toHaveCount(3);
    await expect(history.getByRole("row").nth(1)).toContainText("Oliver wants payroll checked first");
    await expect(history.getByRole("row").nth(1)).toContainText("Confirmed duplicate; note:");
    await expect(history.getByRole("row").nth(1)).toContainText("Needs follow-up; note:");

    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    const row = page.getByRole("row").filter({ has: page.getByRole("button", { name: PETER }) });
    await expect(row).toContainText("Review outcome: Needs follow-up");

    // After a reload the outcome is still saved and the browser remembers the reviewer label.
    await page.reload();
    await page.getByRole("button", { name: PETER }).click();
    await expect(drawer.getByRole("textbox", { name: "Reviewer" })).toHaveValue("Alex Reviewer");
    await expect(pair).toContainText("Saved outcome: Needs follow-up by Alex Reviewer");
  } finally {
    await app.stop();
  }
});

test("a replaced ticket is linked to two kept tickets and both links are shown", async ({ page }, testInfo) => {
  const workbook = writeWorkbook(join(testInfo.outputDir, "three.xlsx"), [
    { number: 1, fields: { Employee: "Ann Smith" } },
    { number: 2, fields: { Employee: "Ann Smith" } },
    { number: 3, fields: { Employee: "Ann Smith" } },
  ]);
  const app = await boot(workbook);
  try {
    await page.goto(app.baseURL);
    const name = "Possible duplicate L000001+L000002+L000003";
    await page.getByRole("button", { name }).click();
    const drawer = page.getByRole("dialog", { name });
    // Three tickets, three pairs, each with its own outcome.
    await expect(drawer.getByRole("form", { name: /\(row \d\) and / })).toHaveCount(3);

    await drawer.getByRole("textbox", { name: "Reviewer" }).fill("Sam");
    await drawer.getByRole("combobox", { name: "Replaced ticket" }).selectOption({ label: "L000003 (row 4)" });
    await drawer.getByRole("checkbox", { name: "L000001 (row 2)" }).check();
    await drawer.getByRole("checkbox", { name: "L000002 (row 3)" }).check();
    await drawer.getByRole("button", { name: "Link tickets" }).click();

    const links = drawer.getByRole("list", { name: "Kept and replaced tickets" }).getByRole("listitem");
    await expect(links).toHaveCount(2);
    await expect(links.nth(0)).toContainText("L000003 (row 4) replaced, L000001 (row 2) kept");
    await expect(links.nth(1)).toContainText("L000003 (row 4) replaced, L000002 (row 3) kept");
    await expect(drawer.getByRole("table", { name: /newest first/ }).getByRole("row")).toHaveCount(3);
  } finally {
    await app.stop();
  }
});
