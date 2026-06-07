import { expect, test } from "@playwright/test";
import { checkoutFoundations } from "./helpers";

test("a conversation is durable and the session is resumable", async ({ page }) => {
  await checkoutFoundations(page);

  // talk to the companion — the stream is persisted server-side as it streams
  await page.getByPlaceholder("Teach me about…").fill("durability test topic");
  await page.getByRole("button", { name: "Send" }).click();
  const say = page.getByText(/new idea|seen this/i).first();
  await expect(say).toBeVisible({ timeout: 20000 });

  // back to the home — the session appears under "Continue a session"
  await page.getByRole("link", { name: "Library" }).click();
  await expect(page).toHaveURL(/\/library/);
  const sessions = page.getByLabel("Your sessions");
  await expect(sessions).toBeVisible();

  // simulate a fresh tab / new device: drop the local cache, then resume
  await page.evaluate(() => sessionStorage.clear());
  await sessions.getByText("The Foundations").first().click();
  await expect(page).toHaveURL(/\/learn\//);

  // the transcript is rebuilt from the durable server-side log
  await expect(page.getByText(/new idea|seen this/i).first()).toBeVisible({ timeout: 15000 });
});
