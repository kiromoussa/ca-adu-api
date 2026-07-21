"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import RapidApiCta from "./RapidApiCta";
import Logo from "./Logo";

const LINKS = [
  { href: "/coverage", label: "Coverage" },
  { href: "/docs", label: "Docs" },
  { href: "/pricing", label: "Pricing" },
  { href: "/changelog", label: "Changelog" },
];

export default function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper/80 backdrop-blur">
      <div className="mx-auto flex max-w-content items-center justify-between gap-4 px-6 py-3.5">
        <Logo />

        <nav className="hidden items-center gap-7 md:flex">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`cursor-pointer font-mono text-[13px] uppercase tracking-[0.08em] transition-colors ${
                  active
                    ? "text-accent-deep"
                    : "text-muted hover:text-ink"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="hidden md:block">
          <RapidApiCta />
        </div>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle navigation menu"
          aria-expanded={open}
          className="cursor-pointer rounded-card border border-line-strong px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink md:hidden"
        >
          Menu
        </button>
      </div>

      {open && (
        <nav className="border-t border-line px-6 py-4 md:hidden">
          <ul className="flex flex-col gap-3">
            {LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className="cursor-pointer font-mono text-sm uppercase tracking-[0.08em] text-muted"
                >
                  {link.label}
                </Link>
              </li>
            ))}
            <li className="pt-2">
              <RapidApiCta className="w-full" />
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
