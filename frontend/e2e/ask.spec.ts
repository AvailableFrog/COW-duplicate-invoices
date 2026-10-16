// Ticket #42: questions in words on the Explore tab, answered through a scripted stand-in for the local model.
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";

import { COMMITTED_WORKBOOK, boot, expect, startScriptedModel, test, type RunningApp, type ScriptedModel } from "./app";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const SLOW = "Show the claimed hours by occupation, slowly.";

let model: ScriptedModel;
let app: RunningApp;

test.beforeAll(async () => {
  model = await startScriptedModel({ [SLOW]: { sleep: 30, answer: { kind: "unsupported" } } });
  app = await boot(COMMITTED_WORKBOOK, ["--model", "scripted-model", "--ollama-url", model.url, "--model-timeout", "4"]);
});

test.afterAll(async () => {
  await app.stop();
  await model.stop();
});

async function openExplore(page: Page) {
  await page.goto(app.baseURL);
  await page.getByRole("tab", { name: "Explore" }).click();
  const explore = page.getByRole("region", { name: "Explore" });
  await explore.getByRole("radio", { name: /Start with all data/ }).check();
  const ask = explore.getByRole("region", { name: "Ask the data" });
  return { explore, ask };
}

async function question(ask: Locator, text: string) {
  const form = ask.getByRole("form", { name: "Ask the data" });
  await form.getByRole("textbox", { name: "Question" }).fill(text);
  await form.getByRole("button", { name: "Ask" }).click();
}

test("a question becomes checked chips and a chart, with its interpretation, and a follow-up edits it", async ({ page }) => {
  const { explore, ask } = await openExplore(page);
  await question(ask, "Make a bar chart of pending tickets by supervisor.");
  await expect(explore.getByRole("region", { name: "Source records by Supervisor" })).toContainText("129 tickets");
  await expect(ask.getByRole("status").filter({ hasText: "Interpreted as:" })).toContainText("Source records: the count");
  await expect(explore.getByRole("form", { name: "Chart chips" }).getByRole("combobox", { name: "Group by" })).toHaveValue("Supervisor");
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG).include(".ask").analyze();
  expect(violations.map((v) => v.id)).toEqual([]);

  const follow = ask.getByRole("form", { name: "Follow up on this chart" });
  await follow.getByRole("textbox", { name: "Follow up" }).fill("Restrict it to September and show it as bars.");
  await follow.getByRole("button", { name: "Change the chart" }).click();
  await expect(explore.getByRole("region", { name: "Source records by Week" })).toContainText("2026-09-01");
});

test("a payment question is explained, not charted, and offers the labelled scenario on the Overview", async ({ page }) => {
  const { ask } = await openExplore(page);
  await question(ask, "How much was paid twice?");
  await expect(ask).toContainText("The export holds no payment records");
  await ask.getByRole("button", { name: "Open the labelled base-value scenario in Value context" }).click();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#value-heading")).toBeFocused();
});

test("an ambiguous question asks which duplicates are meant, and a choice charts them", async ({ page }) => {
  const { explore, ask } = await openExplore(page);
  await question(ask, "Show duplicates by supervisor.");
  await expect(ask).toContainText("Which duplicates do you mean?");
  await ask.getByRole("button", { name: /^Flagged duplicates by Supervisor/ }).click();
  await expect(explore.getByRole("region", { name: "Flagged duplicates by Supervisor" })).toBeVisible();
});

test("a question an Overview view answers opens that view", async ({ page }) => {
  const { ask } = await openExplore(page);
  await question(ask, "Plot weekly submissions, split by current approval status.");
  await ask.getByRole("button", { name: "Open Submission and review timing on the Overview" }).click();
  await expect(page.locator("#timing-heading")).toBeFocused();
});

test("invalid model output ends in an explained state and nothing runs", async ({ page }) => {
  const { explore, ask } = await openExplore(page);
  const before = await explore.getByRole("form", { name: "Chart chips" }).getByRole("combobox", { name: "Group by" }).inputValue();
  await question(ask, "Show tickets by occupation.");
  await expect(ask.getByRole("alert")).toContainText("not the JSON object the plan contract asks for");
  await expect(ask.getByRole("alert")).toContainText("Nothing ran");
  await expect(explore.getByRole("form", { name: "Chart chips" }).getByRole("combobox", { name: "Group by" })).toHaveValue(before);
});

test("a slow answer shows progress, can be cancelled, and times out into a recoverable state", async ({ page }) => {
  const { explore, ask } = await openExplore(page);
  await question(ask, SLOW);
  const progress = ask.getByRole("status").filter({ hasText: "Asking scripted-model" });
  await expect(progress).toContainText(/\d+ s/);
  await progress.getByRole("button", { name: "Cancel" }).click();
  await expect(ask.getByRole("alert")).toContainText("Cancelled. Nothing ran");

  // The service gives up after its model timeout (4 s here, 60 s by default) and says so.
  await question(ask, SLOW);
  await expect(ask.getByRole("alert")).toContainText("The model did not answer within 4 seconds.", { timeout: 15_000 });
  // The tab is still usable: the chips run as before.
  await explore.getByRole("button", { name: "Show ticket counts by approval status" }).click();
  await expect(explore.getByRole("region", { name: "Source records by Approval Status" })).toContainText("2,836 tickets");
});
