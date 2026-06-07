import { request } from "@playwright/test";

// Seed the LeCun graph once before the E2E run so the library has spines to list
// and check out. Idempotent on the backend.
const API = process.env.E2E_API_BASE ?? "http://localhost:4100";
const SEED_AUTHOR = "aaaaaaaa-0000-0000-0000-0000000000e2";

export default async function globalSetup() {
  const ctx = await request.newContext();
  const tokenRes = await ctx.post(`${API}/auth/token`, {
    data: { user_id: SEED_AUTHOR, role: "author" },
  });
  if (!tokenRes.ok()) {
    throw new Error(`E2E setup: /auth/token failed (${tokenRes.status()}) — is the backend on ${API}?`);
  }
  const { token } = await tokenRes.json();
  const seedRes = await ctx.post(`${API}/ingest/seed`, {
    data: { path: "artifacts/lecun_seed_graph.json" },
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!seedRes.ok()) {
    throw new Error(`E2E setup: /ingest/seed failed (${seedRes.status()})`);
  }
  await ctx.dispose();
}
