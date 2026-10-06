// The page's states and acceptance examples (plan U3), in a real browser
// running the real engine through Pyodide.
import { expect, test } from "@playwright/test";

const RUN_DONE = 180_000;

async function openSettings(page) {
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Evolve a Mine Train" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Go" })).toBeEnabled();
}

test("a default run ends with a ride, its stats, a download, and the way to the local tool", async ({ page }) => {
  // Covers AE1 and AE4.
  await openSettings(page);
  await page.getByRole("button", { name: "Go" }).click();
  await expect(page.getByRole("heading", { name: "Evolving your ride" })).toBeVisible();
  await expect(page.getByText(/^\d+ of \d+$/)).toBeVisible();

  await expect(page.getByRole("heading", { name: "Your ride", exact: true })).toBeVisible({ timeout: RUN_DONE });
  await expect(page.getByRole("img", { name: "Isometric view of the ride" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Side profile of the ride" })).toBeVisible();
  // The picture turns a quarter at a time, and each view is its own picture.
  const view = page.locator(".iso-label");
  await expect(view).toHaveText("View 1 of 4");
  const before = await page.locator(".iso-frame svg desc").textContent();
  await page.getByRole("button", { name: "Turn left" }).click();
  await expect(view).toHaveText("View 2 of 4");
  await expect(page.locator(".iso-frame svg desc")).not.toHaveText(before);
  await expect(page.getByRole("rowheader", { name: "Top speed" })).toBeVisible();
  const download = page.getByRole("link", { name: "Download the .td6" });
  await expect(download).toHaveAttribute("download", /^generide-mine-train-seed-\d+\.td6$/);
  await expect(page.getByRole("link", { name: "see how to run generide on your machine" }))
    .toHaveAttribute("href", /github\.com\/joshgarlitos\/generide#use-the-web-ui$/);
  await expect(page.locator(".code-line")).toContainText("python evolve_coaster.py");

  // Covers AE6: nothing survives a refresh.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Evolve a Mine Train" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Your ride" })).toHaveCount(0);
});

test("stop waits for the first ride, keeps it, and the next run keeps the settings", async ({ page }) => {
  // Covers AE2 and the new-run control.
  await openSettings(page);
  await page.getByRole("spinbutton", { name: "Station length" }).fill("8");
  await page.getByRole("button", { name: "Go" }).click();

  const stop = page.getByRole("button", { name: "Stop and keep the best ride" });
  await expect(stop).toBeDisabled();
  await expect(stop).toBeEnabled({ timeout: 60_000 });
  await stop.click();

  await expect(page.getByRole("heading", { name: "Your ride (stopped early)" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Isometric view of the ride" })).toBeVisible();
  await expect(page.locator(".code-line")).toContainText("python evolve_coaster.py");

  await page.getByRole("button", { name: "New run" }).click();
  await expect(page.getByRole("spinbutton", { name: "Station length" })).toHaveValue("8");
  // A fresh engine loads after a stop; Go waits for it.
  await expect(page.getByRole("button", { name: "Go" })).toBeEnabled({ timeout: 60_000 });
});

test("a setting out of range is pointed out beside the field", async ({ page }) => {
  await openSettings(page);
  const field = page.getByRole("spinbutton", { name: "Station length" });
  await field.fill("99");
  await field.blur();
  await expect(page.getByText(/Station length must be from 2 to \d+ tiles on this page\./)).toBeVisible();
});

test("a browser without WebAssembly gets a plain message and the repository link", async ({ page }) => {
  // Covers AE5.
  await page.addInitScript(() => { delete globalThis.WebAssembly; });
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "This page needs a desktop browser" })).toBeVisible();
  await expect(page.getByRole("link", { name: "generide on GitHub" })).toBeVisible();
});

test("an engine that fails to download offers a retry and the repository link", async ({ page }) => {
  // Covers AE7.
  await page.route("**/engine-*.zip", (route) => route.abort());
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Something went wrong" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("The demo could not start.")).toBeVisible();
  await expect(page.getByRole("link", { name: "generide on GitHub" })).toBeVisible();

  await page.unroute("**/engine-*.zip");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Evolve a Mine Train" })).toBeVisible({ timeout: 60_000 });
});

test("a failed engine reload after stop keeps the stopped ride on screen", async ({ page }) => {
  await openSettings(page);
  await page.getByRole("button", { name: "Go" }).click();
  const stop = page.getByRole("button", { name: "Stop and keep the best ride" });
  await expect(stop).toBeEnabled({ timeout: 60_000 });
  // The replacement engine that starts on Stop cannot download.
  await page.route("**/engine.json", (route) => route.abort());
  await stop.click();

  await expect(page.getByRole("heading", { name: "Your ride (stopped early)" })).toBeVisible();
  await page.waitForTimeout(5_000);
  await expect(page.getByRole("heading", { name: "Your ride (stopped early)" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download the .td6" })).toBeVisible();

  // The failure shows when the visitor asks for another run.
  await page.getByRole("button", { name: "New run" }).click();
  await expect(page.getByRole("heading", { name: "Something went wrong" })).toBeVisible();
});
