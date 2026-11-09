import { IconEye } from "@/components/icons";
import { cx } from "@/components/ui";
import type { Source } from "@/lib/types";

export function SourceButton({
  source,
  active,
  label,
  onClick,
}: {
  source: Source | null;
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={`Show source for ${label}`}
      title={source ? `Show where ${label} came from` : "No source on the page"}
      className={cx(
        "inline-flex h-8 shrink-0 items-center gap-1 rounded-md border px-2 text-xs",
        active
          ? "border-accent bg-accent-soft text-accent"
          : source
            ? source.found === false
              ? "border-amber/40 text-amber hover:bg-amber-soft"
              : "border-line text-muted hover:text-ink"
            : "border-dashed border-line text-muted/70",
      )}
    >
      <IconEye size={14} />
      <span className="hidden sm:inline">Source</span>
    </button>
  );
}
