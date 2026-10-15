import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { SERVICE_LOG } from "./app";

/** Start each run with an empty service log, so the teardown checks only this run's output. */
export default function globalSetup(): void {
  mkdirSync(dirname(SERVICE_LOG), { recursive: true });
  writeFileSync(SERVICE_LOG, "");
}
