import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("library lists the three seeded LeCun spines", async ({ page }) => {
  await login(page);
  await expect(page.getByText("The Foundations")).toBeVisible();
  await expect(page.getByText("The Conviction")).toBeVisible();
  await expect(page.getByText("The Contrarian Bet")).toBeVisible();
});

test("check out lands on the learning canvas", async ({ page }) => {
  await login(page);
  const card = page.locator("article", { hasText: "The Foundations" });
  await card.getByRole("button", { name: "Check out" }).click();
  await expect(page).toHaveURL(/\/learn\//);
});

test("cold-start curiosity anchors surface question and person nodes", async ({ page }) => {
  await login(page);
  const anchors = page.getByLabel("Curiosity anchors");
  await expect(anchors).toBeVisible();
  // a known question anchor is present (.first() tolerates a persistent dev DB
  // that may hold a same-titled node from a prior test run; CI's DB is fresh)
  const question = anchors.getByText("What is intelligence?").first();
  await expect(question).toBeVisible();
  // starting from an anchor opens a (free-roam) learning canvas
  await question.click();
  await expect(page).toHaveURL(/\/learn\//);
});
