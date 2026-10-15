import { defineConfig, devices } from "@playwright/test";

// Browser smoke tests against the real process: each spec boots the Python
// application itself on an ephemeral loopback port (see e2e/app.ts), so the
// frontend must be built first (npm run build). Assertions are on text, roles
// and keyboard focus, never pixels.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
});
