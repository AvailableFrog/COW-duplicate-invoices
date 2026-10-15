// Ticket #41: importing a workbook chosen in the browser, with a preview.
import AxeBuilder from "@axe-core/playwright";
import { join } from "node:path";

import { COMMITTED_WORKBOOK, boot, expect, test, writeWorkbook } from "./app";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

test("a chosen workbook is previewed, changes nothing until activated, then becomes the active Snapshot", async ({ page }, testInfo) => {
  // Its own copy of the service, since activating changes the active Snapshot.
  const app = await boot(COMMITTED_WORKBOOK);
  try {
    const chosen = writeWorkbook(
      join(testInfo.outputDir, "October export.xlsx"),
      [
        { number: 1, fields: {} },
        { number: 2, fields: { "Approval Status": "Pending" } },
        { number: 3, fields: {} },
      ],
      ["Rate"],
    );
    await page.goto(app.baseURL);
    const header = page.getByRole("banner");
    await expect(header).toContainText("Labour Tickets Export.xlsx");

    await page.getByLabel("Import a workbook (.xlsx)").setInputFiles(chosen);
    const preview = page.getByRole("region", { name: "Preview of October export.xlsx" });
    await expect(preview).toContainText("3 tickets");
    await expect(preview).toContainText("Labour Tickets (1)");
    await expect(preview).toContainText("21 of 22 expected columns found");
    await expect(preview).toContainText("The workbook has no Rate column");
    await preview.getByText("Column mapping").click();
    await expect(preview.getByRole("row", { name: /^Rate/ })).toContainText("Missing");
    const { violations } = await new AxeBuilder({ page }).withTags(WCAG).include(".workbook-import").analyze();
    expect(violations.map((v) => v.id)).toEqual([]);
    // Nothing has changed yet.
    await expect(header).toContainText("Labour Tickets Export.xlsx");

    await preview.getByRole("button", { name: "Make it the active Snapshot" }).click();
    await expect(page.getByRole("status").filter({ hasText: "is now the active Snapshot" })).toContainText(
      "October export.xlsx is now the active Snapshot",
    );
    await expect(header).toContainText("October export.xlsx");
    await expect(preview).toBeHidden();
  } finally {
    await app.stop();
  }
});

test("a workbook the launch would refuse is refused with the reason and the next step, and nothing changes", async ({ page, app }, testInfo) => {
  const chosen = writeWorkbook(join(testInfo.outputDir, "broken.xlsx"), [{ number: 1, fields: {} }], ["Ticket Number"]);
  await page.goto(app.baseURL);
  await page.getByLabel("Import a workbook (.xlsx)").setInputFiles(chosen);
  const alert = page.getByRole("alert").filter({ hasText: "broken.xlsx was not imported" });
  await expect(alert).toContainText("is missing required column: Ticket Number");
  await expect(alert).toContainText("Nothing was imported and the active Snapshot is unchanged.");
  await expect(page.getByRole("banner")).toContainText("Labour Tickets Export.xlsx");
});
