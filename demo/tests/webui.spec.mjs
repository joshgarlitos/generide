// The local web UI's isometric ride view, in a real browser. These tests run
// against `python3 generide_web.py` started by playwright.config.mjs on a
// throwaway run library that demo/tools/seed_webui_library.py fills with two
// finished runs, so no evolution runs here and nothing touches ~/.generide.
import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

const UI = `http://127.0.0.1:${Number(process.env.WEBUI_PORT || 8778)}`;

// The two seeded run ids, newest first as the library lists them.
async function seededIds(request) {
  const response = await request.get(`${UI}/api/runs`);
  expect(response.ok()).toBeTruthy();
  const ids = (await response.json()).runs.map((run) => run.id);
  expect(ids).toHaveLength(2);
  return ids;
}

async function openGraphs(page, request) {
  const [id] = await seededIds(request);
  await page.goto(`${UI}/#/run/${id}?tab=graphs`);
  await expect(page.getByRole("tab", { name: "Graphs", selected: true })).toBeVisible();
  const picture = page.locator(".iso-frame svg");
  await expect(picture).toBeVisible();
  return picture;
}

// A hash of what the picture looks like right now. The animation clock
// advances even when the train is stuck, so only the pixels prove movement
// (docs/solutions/ui-bugs/smil-train-animation-silently-sits-still.md).
async function look(picture) {
  return createHash("sha1").update(await picture.screenshot()).digest("hex");
}

test("the run screen's Graphs tab shows the isometric picture and turns it a quarter at a time", async ({ page, request }) => {
  const picture = await openGraphs(page, request);
  await expect(page.getByRole("img", { name: "Isometric view of the ride" })).toBeVisible();
  const left = page.getByRole("button", { name: "Turn left" });
  const right = page.getByRole("button", { name: "Turn right" });
  await expect(left).toBeVisible();
  await expect(right).toBeVisible();
  const view = page.locator(".iso-label");
  await expect(view).toHaveText("View 1 of 4");

  const first = await picture.locator("desc").textContent();
  await left.click();
  await expect(view).toHaveText("View 2 of 4");
  await expect(picture.locator("desc")).not.toHaveText(first);
  await right.click();
  await expect(view).toHaveText("View 1 of 4");
  await expect(picture.locator("desc")).toHaveText(first);
  await right.click();
  await expect(view).toHaveText("View 4 of 4");
});

test("the train moves on its own", async ({ page, request }) => {
  const picture = await openGraphs(page, request);
  const first = await look(picture);
  await page.waitForTimeout(1500);
  expect(await look(picture)).not.toBe(first);
});

test("with reduced motion the train is still, and Play lap runs a lap without losing keyboard focus", async ({ browser, request }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  const picture = await openGraphs(page, request);
  const play = page.getByRole("button", { name: "Play lap" });
  await expect(play).toBeVisible();

  const first = await look(picture);
  await page.waitForTimeout(1500);
  expect(await look(picture)).toBe(first);

  await play.focus();
  await page.keyboard.press("Enter");
  await expect(play).toHaveAttribute("aria-disabled", "true");
  await expect(play).toBeFocused();
  await page.waitForTimeout(2000);
  expect(await look(picture)).not.toBe(first);

  // Turning the view ends the lap and puts the train back at rest.
  await page.getByRole("button", { name: "Turn left" }).click();
  await expect(page.locator(".iso-label")).toHaveText("View 2 of 4");
  await expect(play).toHaveAttribute("aria-disabled", "false");
  await context.close();
});

test("the compare screen has one pair of turn buttons, and one press turns every picture", async ({ page, request }) => {
  const ids = await seededIds(request);
  await page.goto(`${UI}/#/compare?ids=${ids.join(",")}`);
  const pictures = page.locator(".compare-grid .iso svg");
  await expect(pictures).toHaveCount(2);

  await expect(page.getByRole("button", { name: "Turn left" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Turn right" })).toHaveCount(1);
  await expect(page.locator(".iso-controls")).toHaveCount(1);
  // The controls sit above the grid, not inside it.
  const controls = await page.locator(".iso-controls").boundingBox();
  const grid = await page.locator(".compare-grid").boundingBox();
  expect(controls.y + controls.height).toBeLessThanOrEqual(grid.y);

  const before = await pictures.locator("desc").allTextContents();
  await page.getByRole("button", { name: "Turn left" }).click();
  await expect(page.locator(".iso-label")).toHaveText("View 2 of 4");
  await expect.poll(async () => {
    const after = await pictures.locator("desc").allTextContents();
    return after.length === 2 && after.every((text, i) => text !== before[i]);
  }).toBe(true);
});
