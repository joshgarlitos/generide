// Browser tests for the in-browser page, run against the built site.
// Build first: `python tools/build_demo.py`, then `npx playwright test`
// from demo/. CI does both in .github/workflows/demo.yml.
import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.DEMO_PORT || 8777);

export default defineConfig({
  testDir: "tests",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}/`,
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1 --directory ../_site`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: !process.env.CI,
  },
});
