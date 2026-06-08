"use client";
import { useEffect, useId, useState } from "react";

/** Renders Mermaid source to SVG, lazy-loading the (large) mermaid library only
 *  when a diagram is actually shown. `securityLevel: "strict"` sanitizes the
 *  output; the source is already server-validated. Renders nothing on failure
 *  rather than an error box. */
export function Mermaid({ code }: { code: string }) {
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setFailed(false);
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark =
          typeof document !== "undefined" &&
          document.documentElement.classList.contains("dark");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: dark ? "dark" : "neutral",
        });
        const { svg } = await mermaid.render(`mmd-${reactId}`, code);
        if (!cancelled) setSvg(svg);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, reactId]);

  if (failed) return null;
  if (!svg) return <p className="text-xs italic text-muted">Drawing…</p>;
  return (
    // mermaid renders with securityLevel:"strict", which sanitizes the SVG
    <div
      className="overflow-x-auto rounded-lg border border-border bg-bg p-3 [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
