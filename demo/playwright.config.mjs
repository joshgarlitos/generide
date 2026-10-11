// Browser tests for the in-browser page, run against the built site, and for
// the local web UI, run against a real `generide_web.py` on a throwaway run
// library. Build first: `python tools/build_demo.py`, then
// `npx playwright test` from demo/. CI does both in .github/workflows/demo.yml.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.DEMO_PORT || 8777);
const WEBUI_PORT = Number(process.env.WEBUI_PORT || 8778);
// Set in the environment so the test file's own load reads the same port.
process.env.WEBUI_PORT = String(WEBUI_PORT);
// One throwaway library per run, shared with the server through the
// environment because Playwright loads this file again in each worker.
const LIBRARY = (process.env.GENERIDE_E2E_HOME ||= mkdtempSync(join(tmpdir(), "generide-e2e-")));

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
  webServer: [
    {
      command: `python3 tools/serve.py --port ${PORT} --dir ../_site`,
      url: `http://127.0.0.1:${PORT}/`,
      reuseExistingServer: !process.env.CI,
    },
    {
      // The local web UI, started from the repo root. The seeding script
      // clears and refills the library before the server starts.
      command: `python3 demo/tools/seed_webui_library.py && python3 generide_web.py --port ${WEBUI_PORT} --no-browser`,
      cwd: "..",
      env: { ...process.env, GENERIDE_HOME: LIBRARY },
      url: `http://127.0.0.1:${WEBUI_PORT}/`,
      // A server already on this port would have its own library, not the
      // seeded one, so never reuse it.
      reuseExistingServer: false,
    },
  ],
});
