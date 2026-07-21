import Link from "next/link";

import { SITE_NAME } from "@/lib/constants";

export default function Footer() {
  return (
    <footer className="border-t border-ink/10 dark:border-white/10">
      <div className="mx-auto max-w-content px-6 py-10 text-sm text-ink/60 dark:text-ink-dark/60">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-md">
            <p className="font-medium text-ink dark:text-ink-dark">{SITE_NAME}</p>
            <p className="mt-2">
              Deterministic, source-cited ADU, JADU, and SB 9 preliminary
              feasibility analysis for California parcels. Los Angeles City is
              the current v1 target; see the coverage page for verified status
              of every jurisdiction.
            </p>
          </div>

          <div className="flex gap-10">
            <div className="flex flex-col gap-2">
              <p className="font-medium text-ink dark:text-ink-dark">Product</p>
              <Link href="/coverage" className="cursor-pointer hover:text-ink dark:hover:text-ink-dark">
                Coverage
              </Link>
              <Link href="/docs" className="cursor-pointer hover:text-ink dark:hover:text-ink-dark">
                API docs
              </Link>
              <Link href="/pricing" className="cursor-pointer hover:text-ink dark:hover:text-ink-dark">
                Pricing
              </Link>
              <Link href="/changelog" className="cursor-pointer hover:text-ink dark:hover:text-ink-dark">
                Changelog
              </Link>
            </div>
          </div>
        </div>

        <p className="mt-8 border-t border-ink/10 pt-6 text-xs text-ink/40 dark:border-white/10 dark:text-ink-dark/40">
          Preliminary informational zoning and GIS analysis only - not legal,
          architectural, surveying, engineering, title, environmental, or
          permit advice. See the disclaimer on every page and every API
          response.
        </p>
      </div>
    </footer>
  );
}
