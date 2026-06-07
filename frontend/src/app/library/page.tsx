"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { ThemeToggle } from "@/components/ThemeToggle";
import { createCheckout, listSpines, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import type { SpineSummary } from "@/lib/types";

function LibraryInner() {
  const router = useRouter();
  const [spines, setSpines] = useState<SpineSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    listSpines()
      .then(setSpines)
      .catch((e) => setError(e instanceof ApiError ? e.message : "failed to load spines"));
  }, []);

  const checkout = async (spine: SpineSummary) => {
    setBusyId(spine.id);
    try {
      const co = await createCheckout(spine.id, spine.subject);
      sessionStorage.setItem(`axon.spine.${co.id}`, spine.id);
      router.push(`/learn/${co.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "checkout failed");
      setBusyId(null);
    }
  };

  const signOut = () => {
    clearSession();
    router.replace("/login");
  };

  // group spines by subject for browsing
  const subjects = Array.from(new Set((spines ?? []).map((s) => s.subject)));

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-fg">Library</h1>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            type="button"
            onClick={signOut}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg hover:bg-surface-2"
          >
            Sign out
          </button>
        </div>
      </header>

      {error && <p className="mb-4 text-sm text-warn">{error}</p>}
      {!spines && <p className="text-sm text-muted">Loading spines…</p>}

      {subjects.map((subject) => (
        <section key={subject} className="mb-8">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
            {subject}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {(spines ?? [])
              .filter((s) => s.subject === subject)
              .map((spine) => (
                <article
                  key={spine.id}
                  className="rounded-lg border border-border bg-surface p-4"
                >
                  <h3 className="font-medium text-fg">{spine.title}</h3>
                  {spine.description && (
                    <p className="mt-1 text-sm text-muted">{spine.description}</p>
                  )}
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-xs text-muted">{spine.node_count} nodes</span>
                    <button
                      type="button"
                      onClick={() => checkout(spine)}
                      disabled={busyId === spine.id}
                      className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
                    >
                      {busyId === spine.id ? "Checking out…" : "Check out"}
                    </button>
                  </div>
                </article>
              ))}
          </div>
        </section>
      ))}
    </main>
  );
}

export default function LibraryPage() {
  return (
    <AuthGuard>
      <LibraryInner />
    </AuthGuard>
  );
}
