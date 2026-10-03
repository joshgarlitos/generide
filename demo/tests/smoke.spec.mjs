// The publish gate's timed runs (plan U5): the default request with the
// fixed default seed, and the slowest settings the page allows. Each must
// finish within DEMO_TIME_LIMIT seconds, and the default ride must meet the
// ride bar (R16). The times are printed so the limit can be calibrated on
// the CI runner itself (see docs/devlog.md).
import { expect, test } from "@playwright/test";

const LIMIT_S = Number(process.env.DEMO_TIME_LIMIT || 90);

async function timedRun(page, fill) {
  await page.goto("./");
  await expect(page.getByRole("button", { name: "Go" })).toBeEnabled({ timeout: 60_000 });
  for (const [name, value] of Object.entries(fill)) {
    await page.getByRole("spinbutton", { name, exact: true }).fill(value);
  }
  const started = Date.now();
  await page.getByRole("button", { name: "Go" }).click();
  await expect(page.getByRole("heading", { name: "Your ride", exact: true }))
    .toBeVisible({ timeout: (LIMIT_S + 60) * 1000 });
  return (Date.now() - started) / 1000;
}

test("the default run finishes in time and meets the ride bar", async ({ page }) => {
  const seconds = await timedRun(page, {});
  console.log(`smoke default: ${seconds.toFixed(1)}s (limit ${LIMIT_S}s)`);
  expect(seconds).toBeLessThan(LIMIT_S);
  const row = (label) => page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: label, exact: true }) });
  await expect(row("Completes the circuit")).toContainText("Yes");
  expect(Number(await row("Drops").locator("td").textContent())).toBeGreaterThanOrEqual(1);
  await expect(page.getByRole("link", { name: "Download the .td6" })).toBeVisible();
});

test("the slowest allowed settings finish in time", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("button", { name: "Go" })).toBeEnabled({ timeout: 60_000 });
  const max = async (name) => page.getByRole("spinbutton", { name, exact: true }).getAttribute("max");
  const fill = {
    "Station length": await max("Station length"),
    "Footprint width": await max("Footprint width"),
    "Footprint depth": await max("Footprint depth"),
  };
  const seconds = await timedRun(page, fill);
  console.log(`smoke slowest: ${seconds.toFixed(1)}s (limit ${LIMIT_S}s)`);
  expect(seconds).toBeLessThan(LIMIT_S);
});
