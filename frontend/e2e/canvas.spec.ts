import { expect, test } from "@playwright/test";
import { checkoutFoundations } from "./helpers";

test("the Foundations spine fills the deck as cards and the companion connects", async ({
  page,
}) => {
  await checkoutFoundations(page);
  // Foundations has 10 nodes; they render as cards (no spine/structure shown).
  await expect(page.getByTestId("concept-card")).toHaveCount(10);
  await expect(page.getByText("● live")).toBeVisible();
});

test("the map toggle reveals the underlying graph", async ({ page }) => {
  await checkoutFoundations(page);
  await page.getByRole("button", { name: "map" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(10);
});

test("sending a subject streams companion activity over the WebSocket", async ({ page }) => {
  await checkoutFoundations(page);
  await page.getByPlaceholder("Teach me about…").fill("convolutional networks");
  await page.getByRole("button", { name: "Send" }).click();
  // Structure/status is suppressed, so the WS round-trip shows as the companion's
  // narration or a fresh card. This crosses the real local LLM (plan -> generate),
  // so the timeout is model-sized, not UI-sized.
  await expect(page.getByText(/new idea|seen this|revisit/i).first()).toBeVisible({
    timeout: 45000,
  });
});

test("opening a card reveals hook then body and offers a go-deeper CTA", async ({ page }) => {
  await checkoutFoundations(page);
  await page.getByRole("button", { name: /^Open / }).first().click();
  const dialog = page.getByRole("dialog");
  const reveal = dialog.getByRole("button", { name: "Reveal explanation" });
  await expect(reveal).toBeVisible();
  await reveal.click();
  // The CTA copy rotates, but its accessible name is stable.
  await expect(dialog.getByRole("button", { name: "Explore further" })).toBeVisible();
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
