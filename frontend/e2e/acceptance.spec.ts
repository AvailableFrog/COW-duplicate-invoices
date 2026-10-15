// Ticket #18: release-one acceptance in the browser.
//
// The first and third usability tasks are walked in evidence-drawer.spec.ts
// (investigate C) and explore.spec.ts (build, then refine, the
// pending-by-supervisor chart). This file adds the second task (F and H are
// separate), an accessibility audit of every main state, and each of the six
// explanatory states with the next action it gives.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";

import { REPO_ROOT, boot, expect, tabTo, test, writeWorkbook } from "./app";

const PETER = "Possible duplicate L225526+L225761";
const F = "Possible duplicate L224030+L224175";
const H = "Possible duplicate L225309+L225552";
const J = "Possible duplicate L226276+L226320";
const CLAIMED_HOURS = "Claimed hours by job (Approved, Job Number not 0)";
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function audit(page: Page, label: string, scope?: string): Promise<void> {
  let builder = new AxeBuilder({ page }).withTags(WCAG);
  if (scope) builder = builder.include(scope);
  const { violations } = await builder.analyze();
  const summary = violations.map((v) => `${v.id} (${v.nodes.length}): ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("; ")}`);
  expect(summary, `${label} has accessibility violations`).toEqual([]);
}

/** One field's row of the drawer's transposed source table, matched on its exact field name. */
function sourceRow(drawer: Locator, field: string): Locator {
  const table = drawer.getByRole("table", { name: "Source fields down the side, one column per ticket" });
  return table.getByRole("row").filter({ has: drawer.page().getByRole("rowheader", { name: new RegExp(`^${field}( ?Differs)?$`) }) });
}

async function openOverview(page: Page, baseURL: string): Promise<void> {
  await page.goto(baseURL);
  await expect(page.getByRole("button", { name: PETER })).toBeVisible();
  // The release 1.1 panels load on their own; wait for them so every check covers them too.
  await expect(page.getByRole("region", { name: CLAIMED_HOURS }).locator('[role="graphics-document"]')).toHaveCount(1);
}

async function startExplore(page: Page): Promise<ReturnType<Page["getByRole"]>> {
  await page.getByRole("tab", { name: "Explore" }).click();
  const explore = page.getByRole("region", { name: "Explore" });
  await explore.getByRole("radio", { name: /Start with all data/ }).check();
  return explore;
}

// The second usability task

test("the second usability task: F and H open by keyboard as separate possible duplicates on different dates", async ({
  page,
  app,
}) => {
  await openOverview(page, app.baseURL);

  const openF = page.getByRole("button", { name: F });
  await tabTo(page, openF);
  await page.keyboard.press("Enter");
  const drawerF = page.getByRole("dialog", { name: F });
  await expect(drawerF).toBeVisible();
  await expect(drawerF).toContainText("Same claim submitted twice");
  await expect(sourceRow(drawerF, "Date")).toContainText("2026-09-10");
  // F's own tickets carry one spelling; the drawer's notes may still mention H's to tell them apart.
  await expect(sourceRow(drawerF, "Employee")).not.toContainText("Mariocollymore");
  await page.keyboard.press("Escape");
  await expect(openF).toBeFocused();

  const openH = page.getByRole("button", { name: H });
  await tabTo(page, openH);
  await page.keyboard.press("Enter");
  const drawerH = page.getByRole("dialog", { name: H });
  await expect(drawerH).toBeVisible();
  await expect(sourceRow(drawerH, "Date")).toContainText("2026-09-23");
  await expect(sourceRow(drawerH, "Employee")).toContainText("Mariocollymore");
  await expect(drawerH).not.toContainText("L224030");
  await expect(drawerH).not.toContainText("L224175");
  await page.keyboard.press("Escape");

  // Comparing one ticket from each says they were never compared: different dates are outside the search space.
  const compare = page.getByRole("form", { name: "Compare two tickets" });
  await tabTo(page, compare.getByRole("spinbutton", { name: "First ticket, Excel row" }));
  await page.keyboard.type("2206");
  await page.keyboard.press("Tab");
  await page.keyboard.type("829");
  await tabTo(page, compare.getByRole("button", { name: "Compare" }));
  await page.keyboard.press("Enter");
  const pair = page.getByRole("dialog", { name: /Excel rows (829 and 2206|2206 and 829)/ });
  await expect(pair.getByRole("heading", { name: "Why these tickets are not linked" })).toBeVisible();
  await expect(pair.locator(".drawer-reason")).toContainText("Not compared: the rules only compare tickets on the same Date");
});

// Accessibility

test("the Overview, an evidence drawer, an uncertain time and Explore with its table and source rows pass an automated WCAG audit", async ({
  page,
  app,
}) => {
  await openOverview(page, app.baseURL);
  await audit(page, "Overview");

  await page.getByRole("button", { name: PETER }).click();
  await expect(page.getByRole("dialog", { name: PETER })).toBeVisible();
  await audit(page, "Peter Holder's drawer", "dialog.drawer");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: J }).click();
  await expect(page.getByRole("dialog", { name: J })).toContainText("assumed");
  await audit(page, "J's drawer", "dialog.drawer");
  await page.keyboard.press("Escape");

  const explore = await startExplore(page);
  const result = explore.getByRole("region", { name: "Source records by Approval Status" });
  await expect(result).toContainText("2,836 tickets");
  await result.getByText("View data", { exact: true }).click();
  await result.getByRole("button", { name: "Inspect source rows" }).click();
  await expect(explore.getByRole("region", { name: /^Source rows:/ })).toBeVisible();
  await audit(page, "Explore with its table and source rows");
});

test("every focus stop on the Overview and in the drawer shows a visible focus indicator", async ({ page, app }) => {
  await openOverview(page, app.baseURL);

  const invisible: string[] = [];
  const check = async () => {
    const found = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      if (!element || element === document.body) return null;
      const style = getComputedStyle(element);
      const outlined = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2;
      const shadowed = style.boxShadow !== "none";
      return outlined || shadowed ? "" : `${element.tagName.toLowerCase()}[type=${element.getAttribute("type")}] label=${element.getAttribute("aria-label") ?? element.id} outline=${style.outlineStyle}/${style.outlineWidth}/${style.outlineColor} shadow=${style.boxShadow}`;
    });
    if (found) invisible.push(found);
  };
  for (let stop = 0; stop < 80; stop += 1) {
    await page.keyboard.press("Tab");
    await check();
  }
  await page.getByRole("button", { name: PETER }).click();
  await expect(page.getByRole("dialog", { name: PETER })).toBeVisible();
  for (let stop = 0; stop < 40; stop += 1) {
    await page.keyboard.press("Tab");
    await check();
  }
  expect(invisible).toEqual([]);
});

test("every chart has a table alternative, legible marks, colour never alone and no green", async ({ page, app }) => {
  await openOverview(page, app.baseURL);
  await expect(page.locator('[role="graphics-document"]').first()).toBeVisible();

  // Every Overview chart sits in a section that offers its data as a table.
  const charts = page.locator('[role="graphics-document"]');
  const chartCount = await charts.count();
  expect(chartCount).toBeGreaterThan(0);
  for (let index = 0; index < chartCount; index += 1) {
    const section = charts.nth(index).locator("xpath=ancestor::section[1]");
    await expect(section.getByText("View data", { exact: true }).first()).toBeVisible();
  }

  const findings = await page.evaluate(() => {
    const parse = (value: string): [number, number, number, number] | null => {
      const match = value.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
      if (match) return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])];
      const hex = value.match(/^#([0-9a-f]{6})$/i);
      if (hex) return [parseInt(hex[1].slice(0, 2), 16), parseInt(hex[1].slice(2, 4), 16), parseInt(hex[1].slice(4, 6), 16), 1];
      return null;
    };
    const luminance = ([r, g, b]: number[]) => {
      const channel = (c: number) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    };
    const contrast = (a: number[], b: number[]) => {
      const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
      return (high + 0.05) / (low + 0.05);
    };
    const hue = ([r, g, b]: number[]) => {
      const [rn, gn, bn] = [r / 255, g / 255, b / 255];
      const max = Math.max(rn, gn, bn);
      const min = Math.min(rn, gn, bn);
      const delta = max - min;
      const saturation = max === 0 ? 0 : delta / max;
      if (delta === 0) return { hue: 0, saturation };
      let h = max === rn ? ((gn - bn) / delta) % 6 : max === gn ? (bn - rn) / delta + 2 : (rn - gn) / delta + 4;
      h *= 60;
      return { hue: h < 0 ? h + 360 : h, saturation };
    };
    const white = [255, 255, 255];
    const lowContrastMarks: string[] = [];
    let marksChecked = 0;
    const greens: string[] = [];
    // Chart marks: bars, points and lines need 3:1 against the white chart panel (WCAG 1.4.11).
    for (const mark of Array.from(document.querySelectorAll('[role="graphics-document"] path, [role="graphics-document"] rect'))) {
      const style = getComputedStyle(mark);
      const fill = parse(style.fill);
      if (!fill || fill[3] === 0 || mark.closest('[aria-hidden="true"]')) continue;
      if (mark.getAttribute("class")?.includes("background")) continue;
      const parent = mark.parentElement?.getAttribute("class") ?? "";
      if (/role-axis|role-legend|role-title|background/.test(parent)) continue;
      const opacity = Number(style.fillOpacity || "1") * Number(style.opacity || "1");
      if (opacity < 1) continue;
      marksChecked += 1;
      if (contrast(fill, white) < 3) lowContrastMarks.push(`${style.fill} in ${parent}`);
    }
    // No green anywhere: green must never suggest that a payment was verified.
    for (const element of Array.from(document.querySelectorAll("body *"))) {
      const style = getComputedStyle(element);
      for (const value of [style.color, style.backgroundColor, style.borderTopColor, style.fill, style.stroke]) {
        const rgba = parse(value);
        if (!rgba || rgba[3] === 0) continue;
        const { hue: h, saturation } = hue(rgba);
        if (saturation > 0.3 && h >= 75 && h <= 160) greens.push(`${element.tagName.toLowerCase()} ${value}`);
      }
    }
    // Colour never alone: every tag or marker that is coloured also carries words.
    const wordless = Array.from(document.querySelectorAll(".tag, .badge, .state, .differs"))
      .filter((element) => (element.textContent ?? "").trim() === "" && !element.getAttribute("aria-label"))
      .map((element) => element.outerHTML.slice(0, 80));
    return { marksChecked, lowContrastMarks: [...new Set(lowContrastMarks)], greens: [...new Set(greens)].slice(0, 10), wordless };
  });

  expect(findings.marksChecked).toBeGreaterThan(0);
  expect(findings.lowContrastMarks).toEqual([]);
  expect(findings.greens).toEqual([]);
  expect(findings.wordless).toEqual([]);
});

// The six explanatory states

test("loading: the first screen says what is loading and what to do if it never finishes", async ({ page, app }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/snapshot", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto(app.baseURL);
  const status = page.getByRole("status").filter({ hasText: "Loading the Snapshot header" });
  await expect(status).toContainText("check the terminal where the service is running");
  release();
  await expect(page.getByRole("button", { name: PETER })).toBeVisible();
});

test("empty: a plan matching no tickets says so, shows no zeros and says how to widen it", async ({ page }, testInfo) => {
  const app = await boot(writeWorkbook(join(testInfo.outputDir, "export.xlsx"), [{ number: 1, fields: {} }, { number: 2, fields: {} }]));
  try {
    await page.goto(app.baseURL);
    const explore = await startExplore(page);
    const result = explore.getByRole("region", { name: "Source records by Approval Status" });
    await expect(result).toContainText("2 tickets");
    await explore.getByRole("form", { name: "Chart chips" }).getByRole("combobox", { name: "Range" }).selectOption("previous_month");
    const empty = result.getByRole("status").filter({ hasText: "Nothing to show." });
    await expect(empty).toContainText("an empty result is not a zero");
    await expect(empty).toContainText("Remove a filter or widen the date range");
    await expect(result.locator('[role="graphics-document"]')).toHaveCount(0);
  } finally {
    await app.stop();
  }
});

test("invalid import and stale snapshot: a changed workbook withdraws the chart, and an unreadable one is refused with the next step", async ({
  page,
}, testInfo) => {
  const path = join(testInfo.outputDir, "export.xlsx");
  writeWorkbook(path, [{ number: 1, fields: {} }, { number: 2, fields: { "Approval Status": "Pending" } }]);
  const app = await boot(path);
  try {
    await page.goto(app.baseURL);
    const explore = await startExplore(page);
    const result = explore.getByRole("region", { name: "Source records by Approval Status" });
    await expect(result).toContainText("2 tickets");

    // Stale: the workbook changed, so the displayed numbers are withdrawn until the plan is rerun.
    writeWorkbook(path, [{ number: 1, fields: {} }, { number: 2, fields: {} }, { number: 3, fields: {} }]);
    await page.getByRole("button", { name: "Reimport" }).click();
    await expect(result.getByRole("alert")).toContainText("Its numbers are withdrawn until you run the plan again");
    await expect(result.getByRole("button", { name: "Rerun the plan" })).toBeVisible();

    // Invalid import: an unreadable workbook is refused, the active Snapshot stays, and the message says what to do.
    writeFileSync(path, "this is not a workbook");
    await page.getByRole("button", { name: "Reimport" }).click();
    const status = page.getByRole("status").filter({ hasText: "was not reimported" });
    await expect(status).toContainText("the current Snapshot stays active");
    await expect(status).toContainText("Correct the workbook at the path the service was launched with, then choose Reimport again.");
  } finally {
    await app.stop();
  }
});

test("uncertain parse: a time without AM/PM is shown as ambiguous and assumed, with the next step to confirm it", async ({ page, app }) => {
  await openOverview(page, app.baseURL);
  await page.getByRole("button", { name: J }).click();
  const drawer = page.getByRole("dialog", { name: J });
  await expect(drawer).toContainText("Ambiguous");
  await expect(drawer.getByText("assumed").first()).toBeVisible();
  await expect(drawer.getByText(/^Next step: confirm the start and finish times/)).toHaveCount(2);
});

test("failed query: a plan the service cannot run says so and how to try again", async ({ page, app }) => {
  await page.route("**/api/plans/execute", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "the service could not run the plan" }) }),
  );
  await openOverview(page, app.baseURL);
  const explore = await startExplore(page);
  const alert = explore.getByRole("alert").filter({ hasText: "The plan could not be run" });
  await expect(alert).toContainText("Change a chip to try again, or reload the page.");
});

// Measured timings, recorded and printed, never asserted (PRD section 12: first load under 10 s, ordinary responses under 1 s).

test("measured: first load, a filter change, opening a drawer and drawing an Explore chart in the browser", async ({ page, app }) => {
  const seconds = (started: number) => Math.round((performance.now() - started) / 10) / 100;
  const timings: Record<string, number> = {};

  let started = performance.now();
  await page.goto(app.baseURL);
  await expect(page.getByRole("button", { name: PETER })).toBeVisible();
  await expect(page.locator('[role="graphics-document"]').first()).toBeVisible();
  timings["first load: page open to a usable Overview"] = seconds(started);

  started = performance.now();
  await page.getByRole("form", { name: "Filters" }).getByRole("combobox", { name: "Status" }).selectOption("Pending");
  // Peter Holder's tickets are both Approved, so his possible duplicate leaves the list once the filter applies.
  await expect(page.getByRole("button", { name: PETER })).toHaveCount(0);
  timings["filter change: Status Pending applied to the Overview"] = seconds(started);
  await page.getByRole("form", { name: "Filters" }).getByRole("button", { name: "Clear" }).click();
  await expect(page.getByRole("button", { name: PETER })).toBeVisible();

  started = performance.now();
  await page.getByRole("button", { name: PETER }).click();
  await expect(page.getByRole("dialog", { name: PETER }).getByRole("table", { name: "Source fields down the side, one column per ticket" })).toBeVisible();
  timings["drilldown: evidence drawer for C"] = seconds(started);
  await page.keyboard.press("Escape");

  started = performance.now();
  const explore = await startExplore(page);
  await expect(explore.locator('[role="graphics-document"]')).toHaveCount(1);
  timings["Explore: first chart drawn"] = seconds(started);

  mkdirSync(join(REPO_ROOT, "test-logs"), { recursive: true });
  writeFileSync(join(REPO_ROOT, "test-logs", "e2e-timings.json"), `${JSON.stringify(timings, null, 2)}\n`);
  for (const [label, value] of Object.entries(timings)) console.log(`${label}: ${value}s`);
  expect(Object.keys(timings)).toHaveLength(4);
});
