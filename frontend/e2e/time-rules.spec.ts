import { join } from "node:path";

import { boot, expect, test, writeWorkbook } from "./app";

test("J's drawer shows the apparent afternoon overlap labelled assumed, never asserted", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const name = "Possible duplicate L226276+L226320";
  await page.getByRole("button", { name }).click();
  const drawer = page.getByRole("dialog", { name });

  const edge = drawer.getByRole("listitem").filter({ hasText: "Ambiguous-period comparison between rows 61 and 105" });
  await expect(edge).toBeVisible();
  await expect(edge).toContainText("Overlap cannot be established; assumed readings compared (12:30–16:30, 240 minutes, assumed)");
  await expect(edge).toContainText("cannot be established");
  await expect(drawer.getByText(/^Work periods (overlap|are separate)/)).toHaveCount(0);
  await expect(drawer.getByRole("list").filter({ hasText: "Possible correction or resubmission" }).first()).toBeVisible();
  await expect(drawer).not.toContainText("Equal duration, separate periods");
  await expect(drawer.getByText("Plausible Reading", { exact: false }).first()).toBeVisible();
});

test("comparing A's two tickets says why they are separate work and not linked", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const compare = page.getByRole("form", { name: "Compare two tickets" });
  await compare.getByRole("spinbutton", { name: "First ticket, Excel row" }).fill("591");
  await compare.getByRole("spinbutton", { name: "Second ticket, Excel row" }).fill("593");
  const button = compare.getByRole("button", { name: "Compare" });
  await button.press("Enter");

  const drawer = page.getByRole("dialog", { name: "Excel rows 591 and 593" });
  await expect(drawer.getByRole("heading", { name: "Why these tickets are not linked" })).toBeVisible();
  await expect(drawer.locator(".drawer-reason")).toContainText("separate work periods");
  await expect(drawer).toContainText("Work periods are separate");
  await expect(drawer.getByRole("list", { name: "Each rule's verdict" }).getByRole("listitem")).toHaveCount(4);
  await expect(drawer.getByRole("heading", { name: "Evidence report example A: Romarian Alleyne: different jobs" })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(button).toBeFocused();
});

test("a three-ticket possible duplicate shows both overlap edges and calls no ticket redundant", async ({ page }, testInfo) => {
  const workbook = writeWorkbook(join(testInfo.outputDir, "three.xlsx"), [
    { number: 1, fields: { Employee: "Ann Smith", "Job Number": 41215, Time: "7:30am-4:30pm", "Regular Hours": 8 } },
    { number: 2, fields: { Employee: "Ann Smith", "Job Number": 20105, Time: "7:30am-11:30am", "Regular Hours": 4 } },
    { number: 3, fields: { Employee: "Ann Smith", "Job Number": 20125, Time: "12:30pm-4:30pm", "Regular Hours": 4 } },
  ]);
  const app = await boot(workbook);
  try {
    await page.goto(app.baseURL);
    const name = "Possible duplicate L000001+L000002+L000003";
    await page.getByRole("button", { name }).click();
    const drawer = page.getByRole("dialog", { name });

    const edges = drawer.locator(".candidates > li");
    await expect(edges).toHaveCount(2);
    await expect(edges.nth(0)).toContainText("Work-period conflict between rows 2 and 3");
    await expect(edges.nth(0)).toContainText("07:30–11:30");
    await expect(edges.nth(1)).toContainText("Work-period conflict between rows 2 and 4");
    await expect(edges.nth(1)).toContainText("12:30–16:30");
    await expect(drawer).toContainText("need not repeat each other");
    await expect(drawer).not.toContainText(/redundant/i);
  } finally {
    await app.stop();
  }
});
