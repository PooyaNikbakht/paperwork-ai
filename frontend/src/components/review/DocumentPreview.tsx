"use client";

import { useEffect, useRef, useState } from "react";
import { IconCheckCircle, IconWarn, IconZoomIn, IconZoomOut } from "@/components/icons";
import { cx } from "@/components/ui";
import { apiUrl } from "@/lib/api";
import type { PageInfo } from "@/lib/types";
import type { Selection } from "./selection";

const ZOOMS = [1, 1.5, 2];

export function DocumentPreview({
  pages,
  selection,
  hasTextLayer,
  filename,
}: {
  pages: PageInfo[];
  selection: Selection | null;
  hasTextLayer: boolean;
  filename: string;
}) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(0);
  const [loaded, setLoaded] = useState<Record<number, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  const source = selection?.source ?? null;

  // Jump to the selected source's page (adjusting state during render, not in an effect).
  const [shownSource, setShownSource] = useState(source);
  if (source !== shownSource) {
    setShownSource(source);
    if (source && source.page >= 1 && source.page <= pages.length) setPage(source.page);
  }

  // Bring the highlight into view.
  useEffect(() => {
    if (!boxRef.current || !scrollRef.current) return;
    const container = scrollRef.current;
    const box = boxRef.current.getBoundingClientRect();
    const rect = container.getBoundingClientRect();
    const top = container.scrollTop + box.top - rect.top - rect.height / 3;
    const left = container.scrollLeft + box.left - rect.left - rect.width / 4;
    container.scrollTo({ top: Math.max(0, top), left: Math.max(0, left), behavior: "smooth" });
  }, [selection, page, zoom, loaded]);

  const info = pages[page - 1];
  const boxes = source && source.page === page ? source.boxes : [];

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-line bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex min-w-0 items-center gap-1" role="tablist" aria-label="Pages">
          {pages.length > 1 ? (
            pages.map((p) => (
              <button
                key={p.number}
                role="tab"
                aria-selected={page === p.number}
                onClick={() => setPage(p.number)}
                className={cx(
                  "h-7 min-w-7 rounded-md px-2 text-xs font-medium",
                  page === p.number ? "bg-ink text-background" : "text-muted hover:bg-background",
                )}
              >
                Page {p.number}
              </button>
            ))
          ) : (
            <span className="truncate px-1 text-xs text-muted">{filename}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setZoom((z) => Math.max(0, z - 1))}
            disabled={zoom === 0}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-background disabled:opacity-40"
            aria-label="Zoom out"
          >
            <IconZoomOut size={16} />
          </button>
          <span className="w-10 text-center font-mono text-xs text-muted tabular">{Math.round(ZOOMS[zoom] * 100)}%</span>
          <button
            onClick={() => setZoom((z) => Math.min(ZOOMS.length - 1, z + 1))}
            disabled={zoom === ZOOMS.length - 1}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-background disabled:opacity-40"
            aria-label="Zoom in"
          >
            <IconZoomIn size={16} />
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto p-3 sm:p-4">
        {info && (
          <div className="relative mx-auto bg-background" style={{ width: `${ZOOMS[zoom] * 100}%` }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={apiUrl(info.url)}
              alt={`Page ${page} of ${filename}`}
              width={info.width}
              height={info.height}
              onLoad={() => setLoaded((l) => ({ ...l, [page]: true }))}
              className={cx("block h-auto w-full border border-line", !loaded[page] && "animate-pulse-soft bg-surface-2")}
            />
            {boxes.map((b, i) => (
              <div
                key={i}
                ref={i === 0 ? boxRef : undefined}
                className="pointer-events-none absolute rounded-[3px] border-2 border-accent"
                style={{
                  left: `calc(${b.x0 * 100}% - 4px)`,
                  top: `calc(${b.y0 * 100}% - 3px)`,
                  width: `calc(${(b.x1 - b.x0) * 100}% + 8px)`,
                  height: `calc(${(b.y1 - b.y0) * 100}% + 6px)`,
                  background: "var(--highlight)",
                }}
              />
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-line px-3 py-2.5 text-xs" aria-live="polite">
        {selection ? (
          <div className="flex items-start gap-2">
            {source?.found === false ? (
              <IconWarn size={15} className="mt-px shrink-0 text-amber" />
            ) : source ? (
              <IconCheckCircle size={15} className="mt-px shrink-0 text-accent" />
            ) : (
              <IconWarn size={15} className="mt-px shrink-0 text-muted" />
            )}
            <div className="min-w-0">
              <p className="font-medium">
                {selection.label}
                {source && <span className="font-normal text-muted"> · page {source.page}</span>}
              </p>
              {source ? (
                <>
                  <p className="mt-0.5 break-words font-mono text-[11px] text-ink">&ldquo;{source.quote}&rdquo;</p>
                  <p className="mt-0.5 text-muted">
                    {source.found === false
                      ? "This quote isn't in the page's text. Check the value by eye."
                      : source.boxes.length
                        ? hasTextLayer
                          ? "Found in the page's text and highlighted."
                          : "Highlighted where it was read."
                        : "No position for this quote on a scan. Compare by eye."}
                  </p>
                </>
              ) : (
                <p className="mt-0.5 text-muted">No source: the AI didn&apos;t find this on the document.</p>
              )}
            </div>
          </div>
        ) : (
          <p className="text-muted">Select &ldquo;Source&rdquo; next to any value to see where it came from.</p>
        )}
      </div>
    </div>
  );
}
