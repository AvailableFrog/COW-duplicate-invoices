import { boot, COMMITTED_WORKBOOK, expect, tabTo, test } from "./app";

test("a readiness count opens by keyboard, lists exactly its tickets and opens one in the drawer", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const readiness = page.getByRole("region", { name: "Data readiness" });
  await expect(readiness).toContainText("Which records cannot be reliably compared or valued?");

  const rates = readiness.getByRole("button", { name: "Missing rates: 129 tickets. List them" });
  await tabTo(page, rates, 400);
  await page.keyboard.press("Enter");
  await expect(rates).toHaveAttribute("aria-pressed", "true");
  const heading = readiness.getByRole("heading", { name: "Missing rates: 129 tickets" });
  await expect(heading).toBeFocused();
  const list = readiness.getByRole("region", { name: "Missing rates: 129 tickets" });
  await expect(list).toContainText("Exactly the 129 tickets counted");
  await expect(list).toContainText("122 of them claim positive hours");
  const tickets = list.getByRole("button", { name: /^Ticket .*, missing rates$/ });
  await expect(tickets).toHaveCount(129);

  const first = tickets.first();
  await tabTo(page, first);
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Why this ticket is shown on its own");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(first).toBeFocused();

  await list.getByRole("button", { name: "Close list" }).click();
  await expect(rates).toBeFocused();
});

test("the reporting window is visible, changes the out-of-window count and resets to the Created years", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const readiness = page.getByRole("region", { name: "Data readiness" });
  await expect(readiness).toContainText("1 January 2026 to 31 December 2026, both ends included");
  const dates = readiness.getByRole("button", { name: /^Dates outside the reporting window: / });
  await expect(dates).toHaveAccessibleName("Dates outside the reporting window: 3 tickets. List them");

  await dates.click();
  const list = readiness.getByRole("region", { name: "Dates outside the reporting window: 3 tickets" });
  await expect(list.getByRole("row").filter({ hasText: "756" })).toContainText("Date 2036-09-29");
  await expect(list.getByText("Date 2050-12-31")).toHaveCount(2);

  await readiness.getByLabel("From").fill("2026-09-01");
  await readiness.getByRole("button", { name: "Apply window" }).click();
  await expect(readiness).toContainText("1 September 2026 to 31 December 2026");
  await expect(readiness).toContainText("set by the analyst");
  await expect(dates).not.toHaveAccessibleName("Dates outside the reporting window: 3 tickets. List them");
  const count = Number((await dates.locator(".tile-value").innerText()).replace(/,/g, ""));
  expect(count).toBeGreaterThan(3);
  await expect(readiness.getByRole("button", { name: /^Ticket .*, dates outside the reporting window$/ })).toHaveCount(count);

  await readiness.getByRole("button", { name: "Use the Created years" }).click();
  await expect(dates).toHaveAccessibleName("Dates outside the reporting window: 3 tickets. List them");
});

test("N's description dates show as a date conflict and in the drawer, beside its recorded Date", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const readiness = page.getByRole("region", { name: "Data readiness" });
  await readiness.getByRole("button", { name: /^Date conflicts in descriptions: / }).click();
  const n = readiness.getByRole("row").filter({ hasText: "L224653" });
  await expect(n).toContainText("7th of September reads as 7 September (no year written) · differs from Date");
  await expect(n).toContainText("uncertain");

  await readiness.getByRole("button", { name: "Ticket L224654, date conflicts in descriptions" }).click();
  const drawer = page.getByRole("dialog", { name: "Ticket L224654" });
  await expect(drawer).toContainText("in no possible duplicate");
  const section = drawer.getByRole("region", { name: "Dates in the description" });
  await expect(section).toContainText("Date 2026-09-11, kept as recorded");
  await expect(section).toContainText("9th September 2026 reads as 9 September 2026 · differs from Date");
  await expect(section).toContainText("on its own it never links tickets");
});

test("the unresolved name proposal drops once it is confirmed in its possible duplicate", async ({ page }) => {
  // A fresh process and data directory, so the decision cannot leak into other specs.
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    await page.goto(app.baseURL);
    const readiness = page.getByRole("region", { name: "Data readiness" });
    const proposals = readiness.getByRole("button", { name: /^Unresolved name proposals: / });
    await expect(proposals).toHaveAccessibleName("Unresolved name proposals: 1 proposed Alias. List them");
    await proposals.click();
    await readiness.getByRole("button", { name: "Decide whether Mario Collymore and Mariocollymore are one person" }).click();

    const drawer = page.getByRole("dialog", { name: "Possible duplicate L225309+L225552" });
    const alias = drawer.getByRole("form", { name: "Proposed Alias: “Mario Collymore” and “Mariocollymore”" });
    await drawer.getByRole("textbox", { name: "Reviewer" }).fill("Alex Reviewer");
    await alias.getByRole("textbox", { name: "Reason for this decision (required)" }).fill("Oliver confirmed one person");
    await alias.getByRole("button", { name: "Confirm Alias" }).click();
    await expect(alias).toContainText("Decision: Confirmed by Alex Reviewer");
    await page.keyboard.press("Escape");

    await expect(proposals).toHaveAccessibleName("Unresolved name proposals: 0 proposed Aliases. List them");
    await expect(readiness).toContainText("Nothing to list under these filters.");
  } finally {
    await app.stop();
  }
});
