import { expect, test } from "@playwright/test";
import { checkoutFoundations } from "./helpers";

test("the Foundations spine renders on the canvas and the companion connects", async ({
  page,
}) => {
  await checkoutFoundations(page);
  // Foundations has 10 nodes; they stream onto the React Flow canvas.
  await expect(page.locator(".react-flow__node")).toHaveCount(10);
  await expect(page.getByText("● live")).toBeVisible();
});

test("sending a subject streams companion activity over the WebSocket", async ({ page }) => {
  await checkoutFoundations(page);
  await page.getByPlaceholder("Teach me about…").fill("convolutional networks");
  await page.getByRole("button", { name: "Send" }).click();
  // the Tutor emits a status before any model call — proves the WS round-trips
  await expect(page.getByText(/checking the library/i)).toBeVisible();
});

test("opening a node reveals hook then body and offers pull-thread", async ({ page }) => {
  await checkoutFoundations(page);
  await page.locator(".react-flow__node").first().click();
  const reveal = page.getByRole("button", { name: "Reveal explanation" });
  await expect(reveal).toBeVisible();
  await reveal.click();
  await expect(page.getByRole("button", { name: /Pull this thread/ })).toBeVisible();
});

test("theme toggle flips light/dark and persists across reload", async ({ page }) => {
  await checkoutFoundations(page);
  const html = page.locator("html");
  await expect(html).toHaveClass(/dark/); // default theme is dark
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect(html).not.toHaveClass(/dark/);
  await page.reload();
  await expect(html).not.toHaveClass(/dark/); // persisted via next-themes
});
