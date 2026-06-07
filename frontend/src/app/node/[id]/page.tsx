"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getNodeSubgraph, ApiError, type SubgraphDTO } from "@/lib/api";
import { kindGlyph } from "@/lib/kind";
import type { EdgeDTO, NodeDTO } from "@/lib/types";

interface Relation {
  edge: EdgeDTO;
  neighbor: NodeDTO;
  outgoing: boolean;
}

function NodeDetailInner({ nodeId }: { nodeId: string }) {
  const [data, setData] = useState<SubgraphDTO | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    getNodeSubgraph(nodeId)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "failed to load node"));
  }, [nodeId]);

  const focal = data?.nodes.find((n) => n.id === nodeId) ?? null;
  const byId = new Map((data?.nodes ?? []).map((n) => [n.id, n]));
  const relations: Relation[] = (data?.edges ?? [])
    .map((edge) => {
      const outgoing = edge.src_node === nodeId;
      const neighborId = outgoing ? edge.dst_node : edge.src_node;
      const neighbor = byId.get(neighborId);
      return neighbor ? { edge, neighbor, outgoing } : null;
    })
    .filter((r): r is Relation => r !== null);

  const attrs = focal?.attributes ? Object.entries(focal.attributes) : [];

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="mb-6 flex items-center justify-between">
        <Link href="/library" className="text-sm text-muted hover:text-fg">
          ← Library
        </Link>
        <ThemeToggle />
      </header>

      {error && <p className="text-sm text-warn">{error}</p>}
      {!data && !error && <p className="text-sm text-muted">Loading…</p>}

      {focal && (
        <article>
          <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-muted">
            <span className="text-accent">{kindGlyph(focal.kind)}</span>
            <span>{focal.kind}</span>
            <span>· {focal.origin}</span>
            {typeof focal.confidence === "number" && <span>· conf {focal.confidence.toFixed(2)}</span>}
            {focal.locked && <span>· locked</span>}
          </div>
          <h1 className="text-2xl font-semibold text-fg">{focal.title}</h1>

          {focal.hook && <p className="mt-3 text-fg">{focal.hook}</p>}
          {focal.body && (
            <p className="mt-3 whitespace-pre-wrap text-sm text-muted">{focal.body}</p>
          )}

          {attrs.length > 0 && (
            <dl className="mt-4 grid grid-cols-[8rem_1fr] gap-1 rounded-md border border-border bg-surface p-3 text-sm">
              {attrs.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd className="text-fg">{Array.isArray(v) ? v.join(", ") : String(v)}</dd>
                </div>
              ))}
            </dl>
          )}

          <section className="mt-6">
            <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">
              Connections{relations.length > 0 ? ` · ${relations.length}` : ""}
            </h2>
            {relations.length === 0 ? (
              <p className="text-sm text-muted">No edges to other nodes yet.</p>
            ) : (
              <ul className="space-y-1">
                {relations.map((r) => (
                  <li key={r.edge.id}>
                    <Link
                      href={`/node/${r.neighbor.id}`}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2"
                    >
                      <span className="w-44 shrink-0 text-xs text-muted">
                        {r.outgoing ? `${r.edge.type} →` : `← ${r.edge.type}`}
                      </span>
                      <span className="text-accent">{kindGlyph(r.neighbor.kind)}</span>
                      <span className="text-fg">{r.neighbor.title}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </article>
      )}
    </main>
  );
}

export default function NodeDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <AuthGuard>
      <NodeDetailInner nodeId={params.id} />
    </AuthGuard>
  );
}
