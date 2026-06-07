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
