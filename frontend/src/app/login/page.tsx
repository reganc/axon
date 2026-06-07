"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { issueToken, ApiError } from "@/lib/api";
import { saveSession } from "@/lib/auth";
import type { Role } from "@/lib/types";

function randomUuid(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "00000000-0000-4000-8000-000000000000";
}

export default function LoginPage() {
  const router = useRouter();
  const [userId, setUserId] = useState(randomUuid());
  const [role, setRole] = useState<Role>("learner");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      const token = await issueToken(userId, role);
      saveSession({ token, userId, role });
      router.push("/library");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "could not reach the API");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-6 shadow-sm">
        <h1 className="text-2xl font-semibold text-fg">AXON</h1>
        <p className="mt-1 text-sm text-muted">Dev sign-in — pick a role to get a token.</p>

        <label className="mt-5 block text-xs font-medium uppercase tracking-wide text-muted">
          User id
        </label>
        <input
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="mt-1 w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        />

        <label className="mt-4 block text-xs font-medium uppercase tracking-wide text-muted">
          Role
        </label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
          className="mt-1 w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        >
          <option value="learner">learner</option>
          <option value="author">author</option>
          <option value="admin">admin</option>
        </select>

        {error && <p className="mt-3 text-sm text-warn">{error}</p>}

        <button
          type="button"
          onClick={signIn}
          disabled={busy}
          className="mt-5 w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </main>
  );
}
