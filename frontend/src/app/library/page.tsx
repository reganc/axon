"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  createCheckout,
  getFacets,
  listCheckouts,
  listEntryPoints,
  listNodes,
  listSpines,
  searchNodes,
  ApiError,
} from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { kindGlyph } from "@/lib/kind";
import type { CheckoutSummary, Facets, NodeDTO, SpineSummary } from "@/lib/types";

function LibraryInner() {
  const router = useRouter();
  const [spines, setSpines] = useState<SpineSummary[] | null>(null);
  const [anchors, setAnchors] = useState<NodeDTO[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [sessions, setSessions] = useState<CheckoutSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // search / browse-results overlay
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<NodeDTO[] | null>(null);
  const [resultsLabel, setResultsLabel] = useState("");
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    listSpines()
      .then(setSpines)
      .catch((e) => setError(e instanceof ApiError ? e.message : "failed to load spines"));
    listEntryPoints().then(setAnchors).catch(() => {});
    getFacets().then(setFacets).catch(() => {});
    listCheckouts().then(setSessions).catch(() => {});
  }, []);

  const resume = (s: CheckoutSummary) => {
    if (s.spine_id) sessionStorage.setItem(`axon.spine.${s.id}`, s.spine_id);
    sessionStorage.setItem(
      `axon.spine.title.${s.id}`,
      s.spine_title ?? s.subject ?? "Session",
    );
    router.push(`/learn/${s.id}`);
  };

  const runSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    try {
      const hits = await searchNodes(q, undefined);
      setResults(hits.map((h) => h.node));
      setResultsLabel(`Results for “${q}”`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "search failed");
    } finally {
      setSearching(false);
    }
  };

  const browseKind = async (kind: string) => {
    setSearching(true);
    try {
      setResults(await listNodes([kind], 60));
      setResultsLabel(`All ${kind} nodes`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "browse failed");
    } finally {
      setSearching(false);
    }
  };

  const clearResults = () => {
    setResults(null);
    setQuery("");
  };

  const checkout = async (spine: SpineSummary) => {
    setBusyId(spine.id);
    try {
      const co = await createCheckout(spine.id, spine.subject);
      sessionStorage.setItem(`axon.spine.${co.id}`, spine.id);
      sessionStorage.setItem(`axon.spine.title.${co.id}`, spine.title);
      router.push(`/learn/${co.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "checkout failed");
      setBusyId(null);
    }
  };

  const startFromAnchor = async (anchor: NodeDTO) => {
    setBusyId(anchor.id);
    try {
      const co = await createCheckout(null, anchor.title);
      sessionStorage.setItem(`axon.spine.title.${co.id}`, anchor.title);
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

  const subjects = Array.from(new Set((spines ?? []).map((s) => s.subject)));

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-5 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-fg">AXON Library</h1>
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

      <div className="mb-6 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
          placeholder="Search the graph…"
          className="flex-1 rounded-md border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={runSearch}
          disabled={searching}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          Search
        </button>
      </div>

      {error && <p className="mb-4 text-sm text-warn">{error}</p>}

      {results ? (
        <section aria-label="Results">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wide text-muted">
              {resultsLabel} · {results.length}
            </h2>
            <button type="button" onClick={clearResults} className="text-sm text-muted hover:text-fg">
              × clear
            </button>
          </div>
          {results.length === 0 ? (
            <p className="text-sm text-muted">Nothing found.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {results.map((n) => (
                <Link
                  key={n.id}
                  href={`/node/${n.id}`}
                  className="rounded-lg border border-border bg-surface p-4 hover:border-accent"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-accent">{kindGlyph(n.kind)}</span>
                    <span className="font-medium text-fg">{n.title}</span>
                  </div>
                  {n.hook && <p className="mt-1 text-sm text-muted">{n.hook}</p>}
                </Link>
              ))}
            </div>
          )}
        </section>
      ) : (
        <>
          {!spines && <p className="text-sm text-muted">Loading…</p>}

          {sessions.length > 0 && (
            <section className="mb-10" aria-label="Your sessions">
              <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
                Continue a session
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {sessions.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => resume(s)}
                    className="rounded-lg border border-border bg-surface p-4 text-left hover:border-accent"
                  >
                    <div className="font-medium text-fg">
                      {s.spine_title ?? s.subject ?? "Free-roam session"}
                    </div>
                    <div className="mt-1 text-xs text-muted">
                      {s.message_count} message{s.message_count === 1 ? "" : "s"}
                      {s.last_activity
                        ? ` · ${new Date(s.last_activity).toLocaleString()}`
                        : ""}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}

          {anchors.length > 0 && (
            <section className="mb-10" aria-label="Curiosity anchors">
              <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
                Start from a curiosity anchor
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {anchors.map((a) => (
                  <div
                    key={a.id}
                    className="rounded-lg border border-border bg-surface p-4"
                  >
                    <Link href={`/node/${a.id}`} className="group">
                      <div className="flex items-center gap-2">
                        <span className="text-accent">{kindGlyph(a.kind)}</span>
                        <span className="font-medium text-fg group-hover:text-accent">{a.title}</span>
                      </div>
                      {a.hook && <p className="mt-1 text-sm text-muted">{a.hook}</p>}
                    </Link>
                    <button
                      type="button"
                      onClick={() => startFromAnchor(a)}
                      disabled={busyId === a.id}
                      className="mt-3 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-50"
                    >
                      Start →
                    </button>
                  </div>
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
                      {g.values.map((v) =>
                        g.dimension === "type" ? (
                          <button
                            key={v.label}
                            type="button"
                            onClick={() => browseKind(v.label)}
                            className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs text-fg hover:border-accent"
                          >
                            {v.label} <span className="text-muted">{v.node_count}</span>
                          </button>
                        ) : (
                          <span
                            key={v.label}
                            className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs text-fg"
                          >
                            {v.label} <span className="text-muted">{v.node_count}</span>
                          </span>
                        ),
                      )}
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
                    <article key={spine.id} className="rounded-lg border border-border bg-surface p-4">
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
        </>
      )}
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
