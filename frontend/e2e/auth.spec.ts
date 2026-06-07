import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("protected route redirects to login when unauthenticated", async ({ page }) => {
  await page.goto("/library");
  await expect(page).toHaveURL(/\/login/);
});

test("login against the identity seam lands on the library", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
});
