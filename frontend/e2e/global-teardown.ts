import { spawnSync } from "node:child_process";
import { join } from "node:path";

import { REPO_ROOT, SERVICE_LOG } from "./app";

const PYTHON = process.env.LTA_PYTHON ?? join(REPO_ROOT, ".venv", "bin", "python");

/** Fail the run if any service printed an employee name, email or description (tests/log_check.py). */
export default function globalTeardown(): void {
  const result = spawnSync(PYTHON, [join(REPO_ROOT, "tests", "log_check.py"), SERVICE_LOG], { cwd: REPO_ROOT, encoding: "utf-8" });
  process.stdout.write(result.stdout);
  if (result.status !== 0) throw new Error(`service logs hold source data:\n${result.stdout}${result.stderr}`);
}
