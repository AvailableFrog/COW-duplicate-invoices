import { expect, tabTo, test } from "./app";

test("the flagged duplicates list filters by counterpart found or unresolved and opens each row by keyboard", async ({
  page,
  app,
}) => {
  await page.goto(app.baseURL);
  const view = page.getByRole("region", { name: "Flagged duplicates" });
  const rows = view.getByRole("button", { name: /^Flagged duplicate / });
  await expect(rows).toHaveCount(28);

  // The tile keeps one count with Oliver's qualification; the split lives in the list.
  const tile = page.locator(".tile").filter({ hasText: "Flagged duplicates" });
  await expect(tile).toContainText("28");
  await expect(tile).toContainText("more than likely a duplicate");

  // The filter is a radio group: Tab reaches it, the arrow keys move through it.
  const all = view.getByRole("radio", { name: "All flagged duplicates (28)" });
  await tabTo(page, all);
  await page.keyboard.press("ArrowRight");
  await expect(view.getByRole("radio", { name: "Counterpart found (16)" })).toBeChecked();
  await expect(rows).toHaveCount(16);
  await page.keyboard.press("ArrowRight");
  await expect(view.getByRole("radio", { name: "Unresolved (12)" })).toBeChecked();
  await expect(rows).toHaveCount(12);
  const m = page.getByRole("button", { name: "Flagged duplicate L224806" });
  await expect(view.getByRole("row").filter({ has: m })).toContainText("Unresolved: no counterpart found");

  // K: an uncertain counterpart, opened by keyboard, with its unresolved AM/PM reading.
  await view.getByRole("radio", { name: "Counterpart found (16)" }).check();
  const k = page.getByRole("button", { name: "Flagged duplicate L224193" });
  await expect(view.getByRole("row").filter({ has: k })).toContainText("Counterpart found, uncertain");
  await tabTo(page, k);
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Possible duplicate L224193+L224194" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Flagged-duplicate counterpart between rows 2187 and 2188");
  await expect(drawer).toContainText("Uncertain counterpart");
  await expect(drawer).toContainText("no AM/PM");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(k).toBeFocused();
});

test("a flagged duplicate no rule links opens on its own, and M shows its later no-hours ticket", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const view = page.getByRole("region", { name: "Flagged duplicates" });
  await view.getByRole("radio", { name: "Unresolved (12)" }).check();

  await view.getByRole("button", { name: "Flagged duplicate L226102" }).click();
  const alone = page.getByRole("dialog", { name: "Flagged duplicate L226102" });
  await expect(alone).toContainText("in no possible duplicate");
  await expect(alone.getByRole("table", { name: "Source fields down the side, one column per ticket" }).getByRole("rowheader")).toHaveCount(22);
  await alone.getByRole("button", { name: "Close" }).click();

  // M: the flagged ticket with hours (L224232, 15 Sep) came before the no-hours one (L224806, 21 Sep).
  await view.getByRole("button", { name: "Flagged duplicate L224806" }).click();
  const m = page.getByRole("dialog", { name: "Possible duplicate L224230+L224232+L224806" });
  await expect(m).toContainText("Repeated component between rows 1575 and 2149");
  await expect(m).toContainText("low-confidence component comparison");
  const timeline = m.getByRole("table", { name: "Tickets in Created order, oldest first" });
  const order = await timeline.getByRole("rowheader").allTextContents();
  expect(order.findIndex((text) => text.startsWith("L224232"))).toBeLessThan(
    order.findIndex((text) => text.startsWith("L224806")),
  );
});
