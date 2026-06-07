"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { ThemeToggle } from "@/components/ThemeToggle";
import { createCheckout, getFacets, listEntryPoints, listSpines, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import type { Facets, NodeDTO, SpineSummary } from "@/lib/types";

function LibraryInner() {
  const router = useRouter();
  const [spines, setSpines] = useState<SpineSummary[] | null>(null);
  const [anchors, setAnchors] = useState<NodeDTO[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    listSpines()
      .then(setSpines)
      .catch((e) => setError(e instanceof ApiError ? e.message : "failed to load spines"));
    listEntryPoints()
      .then(setAnchors)
      .catch(() => {
        /* anchors are optional cold-start sugar; ignore if unavailable */
      });
    getFacets()
      .then(setFacets)
      .catch(() => {
        /* the browse lens is optional; ignore if unavailable */
      });
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

  const startFromAnchor = async (anchor: NodeDTO) => {
    setBusyId(anchor.id);
    try {
      const co = await createCheckout(null, anchor.title); // free-roam, seeded by the anchor
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

      {anchors.length > 0 && (
        <section className="mb-10" aria-label="Curiosity anchors">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
            Start from a curiosity anchor
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {anchors.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => startFromAnchor(a)}
                disabled={busyId === a.id}
                className="rounded-lg border border-border bg-surface p-4 text-left hover:border-accent disabled:opacity-50"
              >
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wide text-accent">{a.kind}</span>
                  <span className="font-medium text-fg">{a.title}</span>
                </div>
                {a.hook && <p className="mt-1 text-sm text-muted">{a.hook}</p>}
              </button>
            ))}
          </div>
        </section>
      )}

      {facets && (
        <section className="mb-10" aria-label="Browse the graph">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
            Browse the graph
            <span className="ml-2 normal-case text-muted">· {facets.node_total} nodes</span>
          </h2>
          <div className="space-y-3">
            {facets.groups
              .filter((g) => g.values.length > 0)
              .map((g) => (
                <div key={g.dimension} className="flex flex-wrap items-center gap-2">
                  <span className="w-16 text-xs uppercase tracking-wide text-muted">
                    {g.dimension}
                  </span>
                  {g.values.map((v) => (
                    <span
                      key={v.label}
                      className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs text-fg"
                    >
                      {v.label} <span className="text-muted">{v.node_count}</span>
                    </span>
                  ))}
                </div>
              ))}
          </div>
        </section>
      )}

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
