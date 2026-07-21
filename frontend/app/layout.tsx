import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "CA ADU Zoning API",
  description:
    "Developer API mapping ADU and housing-density zoning codes for 8 major California cities, validated against state law.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000")
};

function SiteHeader() {
  return (
    <header className="border-b border-surface-border bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-center gap-2 font-semibold text-ink no-underline">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">
            CA
          </span>
          <span>ADU Zoning API</span>
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          <Link href="/#pricing" className="text-ink-soft hover:text-ink no-underline">
            Pricing
          </Link>
          <Link href="/docs" className="text-ink-soft hover:text-ink no-underline">
            API docs
          </Link>
          <Link
            href="/dashboard"
            className="rounded-md bg-brand px-3 py-1.5 font-medium text-white hover:bg-brand-dark no-underline"
          >
            Dashboard
          </Link>
        </nav>
      </div>
    </header>
  );
}

function SiteFooter() {
  return (
    <footer className="border-t border-surface-border bg-white">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-2 px-6 py-6 text-sm text-ink-soft sm:flex-row sm:items-center">
        <span>CA ADU Zoning API - state-law-validated zoning data for California.</span>
        <div className="flex gap-5">
          <Link href="/docs" className="hover:text-ink no-underline">
            Docs
          </Link>
          <Link href="/#pricing" className="hover:text-ink no-underline">
            Pricing
          </Link>
          <Link href="/dashboard" className="hover:text-ink no-underline">
            Dashboard
          </Link>
        </div>
      </div>
    </footer>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col font-sans">
        <SiteHeader />
        <main className="flex-1">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
