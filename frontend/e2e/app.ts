import { spawn, spawnSync } from "node:child_process";
import { appendFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

import { test as base, type Locator, type Page } from "@playwright/test";

export const REPO_ROOT = fileURLToPath(new URL("../../", import.meta.url));
export const COMMITTED_WORKBOOK = join(REPO_ROOT, "data", "Labour Tickets Export.xlsx");
// The project environment that `uv sync` creates; LTA_PYTHON overrides it.
const PYTHON = process.env.LTA_PYTHON ?? join(REPO_ROOT, ".venv", "bin", "python");
const LISTENING_PREFIX = "Listening on ";
// Everything the booted services print, checked in CI for source data by tests/log_check.py.
export const SERVICE_LOG = join(REPO_ROOT, "test-logs", "e2e-service.log");

function record(text: string): void {
  mkdirSync(dirname(SERVICE_LOG), { recursive: true });
  appendFileSync(SERVICE_LOG, text.endsWith("\n") ? text : `${text}\n`);
}

export interface RunningApp {
  baseURL: string;
  fingerprint: string;
  stop: () => Promise<void>;
}

/** Launch the application on an ephemeral loopback port, as a reviewer would, and wait until it listens. */
export async function boot(workbook: string): Promise<RunningApp> {
  const dataDir = mkdtempSync(join(tmpdir(), "lta-e2e-"));
  const child = spawn(PYTHON, ["-m", "labour_ticket_analytics", workbook, "--port", "0", "--data-dir", dataDir], {
    cwd: REPO_ROOT,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const output: string[] = [];
  child.stderr.on("data", (chunk: Buffer) => {
    output.push(chunk.toString());
    record(chunk.toString());
  });
  const baseURL = await new Promise<string>((resolve, reject) => {
    const lines = createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      output.push(line);
      record(line);
      if (line.startsWith(LISTENING_PREFIX)) resolve(line.slice(LISTENING_PREFIX.length).trim());
    });
    child.on("exit", (code) => reject(new Error(`application exited (${code}) before listening:\n${output.join("\n")}`)));
    child.on("error", reject);
  });
  const header = (await (await fetch(`${baseURL}/api/snapshot`)).json()) as { snapshot_fingerprint: string };
  return {
    baseURL,
    fingerprint: header.snapshot_fingerprint,
    stop: async () => {
      if (child.exitCode === null) {
        const exited = new Promise((resolve) => child.once("exit", resolve));
        child.kill();
        await exited;
      }
      rmSync(dataDir, { recursive: true, force: true });
    },
  };
}

/**
 * Write a minimal same-schema workbook with tests/synthetic.py, for shapes the
 * committed export lacks. Each ticket is a number plus field overrides by name; `omit` leaves columns out.
 */
export function writeWorkbook(
  path: string,
  tickets: { number: number; fields: Record<string, string | number | { literal: string }> }[],
  omit: string[] = [],
): string {
  // `{ literal: "=..." }` writes text that begins with "=" as text rather than as a formula.
  const script = [
    "import json, sys",
    "from pathlib import Path",
    "sys.path.insert(0, 'tests')",
    "from synthetic import Literal, ticket, without, write_workbook",
    "spec = json.load(sys.stdin)",
    "value = lambda v: Literal(v['literal']) if isinstance(v, dict) else v",
    "rows = [ticket(t['number'], **{k.replace(' ', '_'): value(v) for k, v in t['fields'].items()}) for t in spec['tickets']]",
    "write_workbook(Path(spec['path']), rows, fields=without(*spec['omit']))",
  ].join("\n");
  mkdirSync(dirname(path), { recursive: true });
  const result = spawnSync(PYTHON, ["-c", script], {
    cwd: REPO_ROOT,
    input: JSON.stringify({ path, tickets, omit }),
    encoding: "utf-8",
  });
  if (result.status !== 0) throw new Error(`could not write the workbook:\n${result.stderr}`);
  return path;
}

/** `app` is the committed workbook, booted once per worker. */
export const test = base.extend<object, { app: RunningApp }>({
  app: [
    async ({}, use) => {
      const app = await boot(COMMITTED_WORKBOOK);
      await use(app);
      await app.stop();
    },
    { scope: "worker" },
  ],
});

export { expect } from "@playwright/test";

/** Press Tab until the named control has focus, proving it is reachable by keyboard alone. */
export async function tabTo(page: Page, target: Locator, limit = 150): Promise<void> {
  for (let presses = 0; presses < limit; presses += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) return;
  }
  throw new Error(`not reached by keyboard within ${limit} Tab presses`);
}
