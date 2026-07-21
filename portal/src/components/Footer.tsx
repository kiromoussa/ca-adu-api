import Link from "next/link";

import { DISCLAIMER_TEXT } from "@/lib/constants";
import { BrandGlyph } from "./Logo";

const PRODUCT_LINKS = [
  { href: "/coverage", label: "Coverage" },
  { href: "/docs", label: "API docs" },
  { href: "/pricing", label: "Pricing" },
  { href: "/changelog", label: "Changelog" },
  { href: "/terms", label: "Terms of Use" },
];

export default function Footer() {
  return (
    <footer className="mt-8 border-t border-line">
      <div className="mx-auto max-w-content px-6 py-12">
        <div className="flex flex-col gap-10 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-measure">
            <div className="flex items-center gap-2.5 text-ink">
              <span className="text-accent">
                <BrandGlyph className="h-5 w-5" />
              </span>
              <span className="text-sm font-bold tracking-tightest">
                Atlas Property Feasibility API
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              The API for property feasibility. Live today for California ADU,
              JADU, and SB 9; expanding to permits, environmental, historic, and
              coastal. Los Angeles City is the current production jurisdiction -
              see coverage for verified status.
            </p>
          </div>

          <nav className="flex flex-col gap-2.5">
            <p className="eyebrow mb-1">Product</p>
            {PRODUCT_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className="cursor-pointer text-sm text-muted transition-colors hover:text-ink"
              >
                {l.label}
              </Link>
            ))}
          </nav>
        </div>

        <p className="mt-10 max-w-measure border-l-2 border-line-strong pl-4 text-xs leading-relaxed text-faint">
          {DISCLAIMER_TEXT}
        </p>

        <p className="mt-6 font-mono text-[11px] uppercase tracking-[0.12em] text-faint">
          Atlas &middot; California &middot; v1 &middot; 2026
        </p>
      </div>
    </footer>
  );
}
