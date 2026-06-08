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

test("search opens a node-detail page with relationships", async ({ page }) => {
  await login(page);
  await page.getByPlaceholder("Search existing cards…").fill("convolution");
  await page.getByRole("button", { name: "Search" }).click();
  const firstResult = page.locator('a[href^="/node/"]').first();
  await expect(firstResult).toBeVisible();
  await firstResult.click();
  await expect(page).toHaveURL(/\/node\//);
  await expect(page.getByText(/Connections/)).toBeVisible();
});

test("a facet type chip drills into a kind list", async ({ page }) => {
  await login(page);
  const browse = page.getByLabel("Browse the graph");
  await browse.getByRole("button", { name: /^person/ }).click();
  await expect(page.getByText(/All person nodes/)).toBeVisible();
  await expect(page.locator('a[href^="/node/"]').first()).toBeVisible();
});

test("browse facets are derived from the graph", async ({ page }) => {
  await login(page);
  const browse = page.getByLabel("Browse the graph");
  await expect(browse).toBeVisible();
  // the type facet reflects the graph's node kinds
  await expect(browse.getByText("concept").first()).toBeVisible();
  await expect(browse.getByText("person").first()).toBeVisible();
});

test("cold-start curiosity anchors surface question and person nodes", async ({ page }) => {
  await login(page);
  const anchors = page.getByLabel("Curiosity anchors");
  await expect(anchors).toBeVisible();
  // a known question anchor is present (.first() tolerates a persistent dev DB
  // that may hold a same-titled node from a prior test run; CI's DB is fresh)
  await expect(anchors.getByText("What is intelligence?").first()).toBeVisible();
  // the anchor title links to its node-detail page…
  await anchors.getByText("What is intelligence?").first().click();
  await expect(page).toHaveURL(/\/node\//);
  // …and "Start →" begins a free-roam learning session
  await page.goBack();
  await anchors.getByRole("button", { name: "Start →" }).first().click();
  await expect(page).toHaveURL(/\/learn\//);
});
