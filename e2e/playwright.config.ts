import { defineConfig } from "@playwright/test";

// Points at a running smspit serving both API and dashboard on one port.
const BASE = process.env.SMSPIT_URL ?? "http://localhost:8025";

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: BASE,
    // Sandboxes with a preinstalled Chromium can point at it directly.
    launchOptions: process.env.PW_EXECUTABLE_PATH
      ? { executablePath: process.env.PW_EXECUTABLE_PATH }
      : {},
  },
  reporter: process.env.CI ? "github" : "list",
});
