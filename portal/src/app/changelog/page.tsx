import type { Metadata } from "next";

import { getApiBaseUrl } from "@/lib/constants";
import type { ChangelogEntry } from "@/lib/types";

export const metadata: Metadata = {
  title: "Changelog",
  description: "Public update history for the ADU Atlas API, by jurisdiction.",
};

// Always fetched fresh: this page reflects live API state, never a
// build-time snapshot or fabricated placeholder data.
export const dynamic = "force-dynamic";

interface ChangelogResult {
  entries: ChangelogEntry[];
  error: string | null;
}

async function fetchChangelog(): Promise<ChangelogResult> {
  const base = getApiBaseUrl();
  if (!base) {
    return {
      entries: [],
      error:
        "NEXT_PUBLIC_API_BASE_URL is not configured, so the live changelog cannot be loaded.",
    };
  }

  try {
    const res = await fetch(`${base}/v1/changelog`, { cache: "no-store" });
    if (!res.ok) {
      return {
        entries: [],
        error: `The API returned status ${res.status} while loading the changelog.`,
      };
    }
    const body = await res.json();
    const entries: ChangelogEntry[] = Array.isArray(body)
      ? body
      : Array.isArray(body?.data)
        ? body.data
        : [];
    return { entries, error: null };
  } catch {
    return {
      entries: [],
      error: "Could not reach the API to load the changelog.",
    };
  }
}

function entryDate(entry: ChangelogEntry): string | null {
  const raw = entry.published_at ?? entry.created_at ?? null;
  if (!raw) return null;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function ChangelogPage() {
  const { entries, error } = await fetchChangelog();

  return (
    <div className="mx-auto max-w-content px-6 py-16">
      <p className="eyebrow">Changelog</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tightest sm:text-4xl">
        What changed, by city.
      </h1>
      <p className="mt-4 max-w-measure leading-relaxed text-muted">
        Source re-ingestions, rule corrections, and coverage-status changes,
        pulled live from GET /v1/changelog.
      </p>

      {error && (
        <div className="mt-8 rounded-card border border-line bg-surface p-5 text-sm text-muted">
          {error}
        </div>
      )}

      {!error && entries.length === 0 && (
        <div className="mt-8 rounded-card border border-line bg-surface p-5 text-sm text-muted">
          No changelog entries yet.
        </div>
      )}

      {entries.length > 0 && (
        <ol className="mt-10 space-y-6">
          {entries.map((entry, index) => (
            <li
              key={entry.id ?? index}
              className="rounded-card border border-line bg-surface p-6"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold tracking-tightest">
                  {entry.title ?? "Update"}
                </h2>
                {entryDate(entry) && (
                  <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-faint">
                    {entryDate(entry)}
                  </span>
                )}
              </div>
              {(entry.jurisdiction_name || entry.jurisdiction_slug) && (
                <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.06em] text-faint">
                  {entry.jurisdiction_name ?? entry.jurisdiction_slug}
                </p>
              )}
              {(entry.summary || entry.description) && (
                <p className="mt-3 text-sm leading-relaxed text-muted">
                  {entry.summary ?? entry.description}
                </p>
              )}
              {entry.category && (
                <span className="mt-3 inline-block rounded-full border border-line bg-surface-2 px-3 py-1 font-mono text-[12px] text-muted">
                  {entry.category}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
