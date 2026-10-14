import { join } from "node:path";

import type { Locator, Page } from "@playwright/test";

import { boot, expect, test, writeWorkbook } from "./app";

const PETER = "Possible duplicate L225526+L225761";

/** Press Tab until the named control has focus, proving it is reachable by keyboard alone. */
async function tabTo(page: Page, target: Locator, limit = 150): Promise<void> {
  for (let presses = 0; presses < limit; presses += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) return;
  }
  throw new Error(`not reached by keyboard within ${limit} Tab presses`);
}

test("the Peter Holder possible duplicate opens from the list by keyboard and its drawer reads end to end", async ({
  page,
  app,
}) => {
  await page.goto(app.baseURL);
  const opener = page.getByRole("button", { name: PETER });
  await expect(opener).toBeVisible();

  await tabTo(page, opener);
  await page.keyboard.press("Enter");

  const drawer = page.getByRole("dialog", { name: PETER });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Close" })).toBeFocused();

  // Why, with the Candidate's rule and fields, and the member-level states.
  await expect(drawer).toContainText("Same claim submitted twice");
  await expect(drawer).toContainText("Strict repeat between rows 620 and 855");
  await expect(drawer).toContainText("2 tickets Approved, Keyed");

  // Annotation C: letter, condensed note and the question for Oliver.
  await expect(drawer.getByRole("heading", { name: "Evidence report example C: Peter Holder: priority example" })).toBeVisible();
  await expect(drawer).toContainText("Keep it as the lead example, but ask Oliver whether it was handled somewhere we cannot see.");
  await expect(drawer.getByRole("listitem").filter({ hasText: "Were these caught or missed?" })).toBeVisible();
  await expect(drawer).toContainText("For Peter’s pair, show which ticket was retained");

  // Timeline in Created order: L225526 (28 Sep) before L225761 (2 Oct).
  const timeline = drawer.getByRole("table", { name: "Tickets in Created order, oldest first" });
  await expect(timeline.getByRole("rowheader")).toHaveText([/^L225526/, /^L225761/]);
  await expect(timeline.getByRole("row").nth(1)).toContainText("2026-09-28 18:21:00");

  // The transposed source table: all 22 fields, the five differing ones marked.
  const source = drawer.getByRole("table", { name: "Source fields down the side, one column per ticket" });
  await expect(source.getByRole("rowheader")).toHaveCount(22);
  await expect(source.getByRole("rowheader").filter({ hasText: "Differs" })).toHaveText([
    "Ticket NumberDiffers",
    "ModifiedDiffers",
    "CreatedDiffers",
    "IDDiffers",
    "Date ApprovedDiffers",
  ]);
  await expect(source.getByRole("row", { name: /^Keyed/ })).toContainText("true");

  // Provenance and the parse result for each member.
  await expect(drawer).toContainText("Excel row 620, dataframe index 618, sheet Labour Tickets (1)");
  await expect(drawer).toContainText("Excel row 855, dataframe index 853, sheet Labour Tickets (1)");
  await expect(drawer).toContainText(app.fingerprint);
  await expect(drawer.getByText("Parser version")).toHaveCount(2);
  await expect(drawer.getByText("7:30 am to 4:30 pm: Confident 07:30–16:30")).toHaveCount(2);

  // Escape closes the drawer and returns focus to the row that opened it.
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(opener).toBeFocused();
});

test("a possible duplicate with no annotated ticket shows no annotation", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const openers = page.getByRole("button", { name: /^Possible duplicate / });
  await expect(openers).toHaveCount(34);
  // Rank 5 is rows 425/1191, the Approved/Pending pair; none of its tickets is in the evidence report.
  await openers.nth(4).click();

  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: "Why these tickets are together" })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: /Evidence report example/ })).toHaveCount(0);
  await expect(drawer).not.toContainText("Questions for Oliver");
});

test("markup in a description renders as literal text and Show whitespace leaves the value unchanged", async ({
  page,
}, testInfo) => {
  const markup = '<b>bold</b> <img src=x onerror="window.__injected = true">\n  indented line';
  const workbook = writeWorkbook(join(testInfo.outputDir, "markup.xlsx"), [
    { number: 1, fields: { Employee: "Ann Smith", "Description of Job Work": markup, "Job Name": "Sandals" } },
    { number: 2, fields: { Employee: "Ann Smith", "Description of Job Work": markup, "Job Name": "Sandals " } },
  ]);
  const app = await boot(workbook);
  try {
    await page.goto(app.baseURL);
    await page.getByRole("button", { name: "Possible duplicate L000001+L000002" }).click();
    const drawer = page.getByRole("dialog", { name: "Possible duplicate L000001+L000002" });
    const source = drawer.getByRole("table", { name: "Source fields down the side, one column per ticket" });
    const description = source.getByRole("row", { name: /^Description of Job Work/ });

    // Exact text content: toHaveText would collapse the whitespace this test is about.
    expect(await description.getByRole("cell").first().textContent()).toBe(markup);
    await expect(drawer.locator("b, img")).toHaveCount(0);
    expect(await page.evaluate(() => (window as { __injected?: boolean }).__injected)).toBeUndefined();

    const jobName = source.getByRole("row", { name: /^Job Name/ });
    await expect(jobName.getByRole("rowheader")).toContainText("Differs");
    expect(await jobName.getByRole("cell").allTextContents()).toEqual(["Sandals", "Sandals "]);

    await drawer.getByRole("checkbox", { name: "Show whitespace" }).check();
    await expect(jobName.getByRole("cell").nth(1)).toHaveText("“Sandals·”");
    expect(await jobName.getByRole("cell").allTextContents()).toEqual(["“Sandals”", "“Sandals·”"]);
    await expect(description.getByRole("cell").first()).toContainText("<b>bold</b>·<img");

    const api = await page.request.get(`${app.baseURL}/api/snapshots/${app.fingerprint}/tickets/3/possible-duplicate`);
    const body = (await api.json()) as { fields: { field: string; cells: { value: unknown }[] }[] };
    const values = body.fields.find((row) => row.field === "Job Name")?.cells.map((cell) => cell.value);
    expect(values).toEqual(["Sandals", "Sandals "]);
  } finally {
    await app.stop();
  }
});
