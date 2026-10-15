import { expect, tabTo, test } from "./app";

interface Totals {
  possible_duplicates: number;
  tickets: number;
}

interface PrioritiesBody {
  possible_duplicates: unknown[];
  pattern_filter: { totals: Totals; counts: (Totals & { id: string })[] };
}

const SAME_CLAIM = "same_claim_twice";
const CORRECTION = "correction_or_resubmission";

test("the matrix is a table with headers and a caption saying pattern counts overlap", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const view = page.getByRole("region", { name: "Review priorities" });
  const matrix = view.getByRole("table", { name: /^Tickets by pattern and source state\. Pattern counts overlap/ });
  await expect(matrix).toBeVisible();

  const columns = await matrix.getByRole("columnheader").allTextContents();
  expect(columns).toEqual([
    "Pattern", "Approved, Keyed", "Approved, not Keyed", "Pending", "Rejected", "Flagged duplicate", "Tickets",
    "Possible duplicates",
  ]);
  const rows = await matrix.getByRole("rowheader").allTextContents();
  expect(rows).toEqual([
    "1. Same claim appears twice", "2. Same claim looks different as text", "3. Possible correction or resubmission",
    "4. Equal duration, separate periods", "5. Repeated payment component", "Any pattern, each ticket once",
  ]);
  // The Any pattern row counts each ticket once: the registry's candidate tickets, 186 on the export.
  await expect(matrix.getByRole("row", { name: /^Any pattern/ })).toContainText("186");
});

test("selecting two patterns by keyboard lists possible duplicates matching either, with union totals", async ({
  page,
  app,
}) => {
  const body = (await (
    await fetch(`${app.baseURL}/api/review-priorities?pattern=${SAME_CLAIM}&pattern=${CORRECTION}`)
  ).json()) as PrioritiesBody;
  const { totals, counts } = body.pattern_filter;
  const own = counts.filter((count) => count.id === SAME_CLAIM || count.id === CORRECTION);
  const sum = (key: keyof Totals) => own.reduce((total, count) => total + count[key], 0);
  // I (318/999/1545) carries both patterns, so the union is smaller than the sum.
  expect(totals.possible_duplicates).toBeLessThan(sum("possible_duplicates"));
  expect(totals.tickets).toBeLessThanOrEqual(sum("tickets"));

  await page.goto(app.baseURL);
  const view = page.getByRole("region", { name: "Review priorities" });
  const filter = view.getByRole("group", { name: "Show patterns" });
  const sameClaim = filter.getByRole("checkbox", { name: "Same claim appears twice" });
  const correction = filter.getByRole("checkbox", { name: "Possible correction or resubmission" });

  await tabTo(page, sameClaim);
  await page.keyboard.press("Space");
  await expect(sameClaim).toBeChecked();
  await tabTo(page, correction);
  await page.keyboard.press("Space");
  await expect(correction).toBeChecked();

  const status = filter.getByRole("status");
  await expect(status).toContainText(
    `Matching: ${totals.possible_duplicates} possible duplicates with ${totals.tickets} tickets inside the filters`,
  );
  await expect(status).toContainText(
    `The 2 patterns' own counts add up to ${sum("possible_duplicates")} and ${sum("tickets")}: they overlap.`,
  );
  const list = view.getByRole("table", { name: /^Possible duplicates in review-priority order/ });
  await expect(list.getByRole("button", { name: /^Possible duplicate / })).toHaveCount(totals.possible_duplicates);
  // I keeps its flagged ticket, which only a pattern-3 link joins; it is shown but not counted for pattern 1 alone.
  const i = list.getByRole("row").filter({ has: page.getByRole("button", { name: "Possible duplicate L224836+L225382+L226063" }) });
  await expect(i).toContainText("Same claim appears twice");
  await expect(i).toContainText("Possible correction or resubmission");
  await expect(i).toContainText("Mixed source states: 1 Approved, Keyed · 1 Rejected · 1 Flagged duplicate");

  // Clearing goes back to every possible duplicate.
  await filter.getByRole("button", { name: "Clear pattern filter" }).press("Enter");
  await expect(sameClaim).not.toBeChecked();
  await expect(status).toContainText("All: 85 possible duplicates with 186 tickets");
});

test("choosing a matrix count lists exactly that many tickets and labels the others", async ({ page, app }) => {
  await page.goto(app.baseURL);
  const view = page.getByRole("region", { name: "Review priorities" });
  const cell = view.getByRole("button", { name: "18 Flagged duplicate tickets, Possible correction or resubmission: show in the list" });
  await tabTo(page, cell);
  await page.keyboard.press("Enter");
  await expect(cell).toHaveAttribute("aria-pressed", "true");

  const filter = view.getByRole("group", { name: "Show patterns" });
  await expect(filter.getByRole("checkbox", { name: "Possible correction or resubmission" })).toBeChecked();
  await expect(filter).toContainText("Only tickets that are Flagged duplicate.");
  await expect(filter.getByRole("status")).toContainText("with 18 tickets inside the filters");
  const list = view.getByRole("table", { name: /^Possible duplicates in review-priority order/ });
  // Each listed possible duplicate keeps its counterpart, labelled as outside the pattern filter.
  await expect(list.getByText("Outside the pattern filter").first()).toBeVisible();
  await expect(cell).toBeFocused();
});
