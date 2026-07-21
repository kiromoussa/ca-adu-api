"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import RapidApiCta from "./RapidApiCta";
import { SITE_NAME } from "@/lib/constants";

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
    <header className="sticky top-0 z-40 border-b border-ink/10 bg-canvas/90 backdrop-blur dark:border-white/10 dark:bg-canvas-dark/90">
      <div className="mx-auto flex max-w-content items-center justify-between gap-4 px-6 py-4">
        <Link
          href="/"
          className="cursor-pointer text-base font-semibold tracking-tight text-ink dark:text-ink-dark"
        >
          {SITE_NAME}
        </Link>

        <nav className="hidden items-center gap-6 md:flex">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`cursor-pointer text-sm transition-colors ${
                  active
                    ? "font-medium text-ink dark:text-ink-dark"
                    : "text-ink/60 hover:text-ink dark:text-ink-dark/60 dark:hover:text-ink-dark"
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
          className="cursor-pointer rounded-md border border-ink/15 px-3 py-1.5 text-sm text-ink dark:border-white/20 dark:text-ink-dark md:hidden"
        >
          Menu
        </button>
      </div>

      {open && (
        <nav className="border-t border-ink/10 px-6 py-4 dark:border-white/10 md:hidden">
          <ul className="flex flex-col gap-3">
            {LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className="cursor-pointer text-sm text-ink/80 dark:text-ink-dark/80"
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
