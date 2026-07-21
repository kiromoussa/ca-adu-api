import { DISCLAIMER_TEXT } from "@/lib/constants";

export default function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-card border border-line bg-surface p-5 ${className}`}
    >
      <p className="eyebrow mb-2">Disclaimer</p>
      <p className="max-w-measure text-sm leading-relaxed text-muted">
        {DISCLAIMER_TEXT}
      </p>
    </div>
  );
}
