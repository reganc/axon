import { expect, type Page } from "@playwright/test";

/** Dev sign-in. The user id field is prefilled with a fresh uuid per page load. */
export async function login(page: Page, role = "learner"): Promise<void> {
  await page.goto("/login");
  await page.locator("select").selectOption(role);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/library/);
}

/** Sign in, then check out the Foundations spine and land on its canvas. */
export async function checkoutFoundations(page: Page): Promise<void> {
  await login(page);
  const card = page.locator("article", { hasText: "The Foundations" });
  await card.getByRole("button", { name: "Check out" }).click();
  await expect(page).toHaveURL(/\/learn\//);
}
