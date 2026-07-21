import Link from "next/link";

// Parcel/contour mark - a lot outline with a plotted point, echoing the
// survey-plate identity. No emoji, currentColor-driven so it themes.
export function BrandGlyph({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      fill="none"
    >
      <rect
        x="1.5"
        y="1.5"
        width="21"
        height="21"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M4 15 L9 9 L14 13 L20 6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="20" cy="6" r="1.9" fill="currentColor" />
    </svg>
  );
}

export default function Logo() {
  return (
    <Link
      href="/"
      className="group flex cursor-pointer items-center gap-2.5 text-ink"
    >
      <span className="text-accent">
        <BrandGlyph className="h-[22px] w-[22px]" />
      </span>
      <span className="text-base font-bold tracking-tightest">Atlas</span>
      <span className="rounded border border-line-strong px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-faint">
        Feasibility API
      </span>
    </Link>
  );
}
