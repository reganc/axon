"use client";
import type { ReactNode } from "react";
import { neighborGraphToMermaid } from "@/lib/mermaidGraph";
import type { MediaItem } from "@/store/transcriptStore";
import { Mermaid } from "./Mermaid";

/** Extract a YouTube video id from a watch/short/embed URL (the URL is already
 *  server-validated via oEmbed, so this only needs to find the id). */
function youtubeId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) return u.pathname.slice(1) || null;
    if (u.pathname.startsWith("/embed/")) return u.pathname.split("/")[2] || null;
    return u.searchParams.get("v");
  } catch {
    return null;
  }
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
      {children}
    </h4>
  );
}

/** The card's visual layer: an embedded explainer video, a generated diagram, a
 *  mini-graph of how the concept connects, reference links, and an image — only
 *  what the companion actually found and validated for this card. */
export function MediaPanel({ items }: { items: MediaItem[] | undefined }) {
  if (!items || items.length === 0) return null;

  const video = items.find((m) => m.kind === "video");
  const diagram = items.find((m) => m.kind === "diagram");
  const graphItem = items.find((m) => m.kind === "graph");
  const links = items.filter((m) => m.kind === "link");
  const images = items.filter((m) => m.kind === "image");
  const vid = video ? youtubeId(video.url) : null;
  const graphCode = graphItem ? neighborGraphToMermaid(graphItem.graph) : null;

  return (
    <section className="mt-5 border-t border-border pt-4" aria-label="Visual aids">
      {vid && (
        <div className="mb-4">
          <SectionLabel>Watch</SectionLabel>
          <div className="aspect-video w-full overflow-hidden rounded-lg border border-border">
            <iframe
              className="h-full w-full"
              src={`https://www.youtube-nocookie.com/embed/${vid}`}
              title="Explainer video"
              loading="lazy"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              referrerPolicy="strict-origin-when-cross-origin"
            />
          </div>
        </div>
      )}

      {diagram && (
        <div className="mb-4">
          <SectionLabel>Diagram</SectionLabel>
          <Mermaid code={diagram.mermaid} />
        </div>
      )}

      {graphCode && (
        <div className="mb-4">
          <SectionLabel>How it connects</SectionLabel>
          <Mermaid code={graphCode} />
        </div>
      )}

      {images.length > 0 && (
        <div className="mb-4">
          <SectionLabel>Illustration</SectionLabel>
          <div className="flex flex-wrap gap-2">
            {images.map((img) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={img.url}
                src={img.url}
                alt=""
                loading="lazy"
                className="max-h-48 rounded-lg border border-border"
              />
            ))}
          </div>
        </div>
      )}

      {links.length > 0 && (
        <div>
          <SectionLabel>Read more</SectionLabel>
          <ul className="flex flex-col gap-1.5">
            {links.map((link) => (
              <li key={link.url}>
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-accent underline-offset-2 hover:underline"
                >
                  {link.title || link.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
