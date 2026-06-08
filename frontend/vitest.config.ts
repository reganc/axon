import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

// Unit tests for pure client logic (stores, lib). jsdom gives the stores the
// `window` / `sessionStorage` they persist into. E2E stays in Playwright.
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
  resolve: {
    alias: { "@": resolve(__dirname, "src") },
  },
});
