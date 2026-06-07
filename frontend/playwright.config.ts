import { defineConfig, devices } from "@playwright/test";

// E2E drives the real browser against a running frontend (:4101) + backend
// (:4100). The backend should run with deterministic embeddings and no model
// host so turns are fast and deterministic (the LLM gateway falls back to its
// built-in fake). global-setup seeds the LeCun graph via the API.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:4101";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run start",
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
