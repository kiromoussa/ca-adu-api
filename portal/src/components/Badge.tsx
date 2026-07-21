import type { CoverageStatus } from "@/lib/types";
import { COVERAGE_STATUS_LABELS } from "@/lib/constants";

const STATUS_STYLES: Record<CoverageStatus, string> = {
  production:
    "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-400 dark:ring-emerald-500/30",
  ingesting:
    "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-500/30",
  planned:
    "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-500/20 dark:bg-slate-500/10 dark:text-slate-400 dark:ring-slate-500/30",
};

export default function CoverageBadge({ status }: { status: CoverageStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.planned;
  const label = COVERAGE_STATUS_LABELS[status] ?? status;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}
    >
      {label}
    </span>
  );
}
