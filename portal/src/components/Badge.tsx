import type { CoverageStatus } from "@/lib/types";
import { COVERAGE_STATUS_LABELS } from "@/lib/constants";

// Status is encoded in both a dot color and the label, so it reads at a glance.
const STATUS: Record<CoverageStatus, { dot: string; text: string }> = {
  production: { dot: "bg-ok", text: "text-ok" },
  ingesting: { dot: "bg-warn", text: "text-warn" },
  planned: { dot: "bg-faint", text: "text-muted" },
};

export default function CoverageBadge({ status }: { status: CoverageStatus }) {
  const s = STATUS[status] ?? STATUS.planned;
  const label = COVERAGE_STATUS_LABELS[status] ?? status;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.06em] ${s.text}`}
    >
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {label}
    </span>
  );
}
