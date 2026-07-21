import { DISCLAIMER_TEXT } from "@/lib/constants";

export default function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-lg border border-ink/10 bg-ink/[0.03] p-5 text-sm leading-relaxed text-ink/80 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-dark/80 ${className}`}
    >
      <p className="mb-1 font-semibold text-ink dark:text-ink-dark">Disclaimer</p>
      <p>{DISCLAIMER_TEXT}</p>
    </div>
  );
}
