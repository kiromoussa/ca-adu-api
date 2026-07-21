"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ApiTier } from "@/lib/database.types";
import { PRICING_TIERS } from "@/lib/pricing";
import { createClient } from "@/lib/supabase/client";
import { createApiKey, revokeApiKey } from "./actions";
import UsageChart, { type UsageBucket } from "./usage-chart";

export interface KeyRow {
  id: string;
  name: string | null;
  key_prefix: string;
  tier: ApiTier;
  revoked: boolean;
  requests_this_month: number;
  created_at: string;
}

export interface DashboardData {
  email: string;
  currentTier: ApiTier;
  quota: number | null;
  requestsThisMonth: number;
  quotaResetAt: string | null;
  billingActive: boolean;
  keys: KeyRow[];
  usage: UsageBucket[];
}

function TierBadge({ tier }: { tier: ApiTier }) {
  const label = tier.charAt(0).toUpperCase() + tier.slice(1);
  return (
    <span className="rounded-full bg-brand/10 px-2.5 py-0.5 text-xs font-semibold text-brand-dark">
      {label}
    </span>
  );
}

export default function DashboardClient({ data }: { data: DashboardData }) {
  const router = useRouter();
  const [keyName, setKeyName] = useState("");
  const [newRawKey, setNewRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [checkoutPending, setCheckoutPending] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const quotaPct =
    data.quota && data.quota > 0
      ? Math.min(100, Math.round((data.requestsThisMonth / data.quota) * 100))
      : 0;

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setActionError(null);
    setNewRawKey(null);
    setCopied(false);
    startTransition(async () => {
      const result = await createApiKey(keyName);
      if (!result.ok) {
        setActionError(result.error ?? "Could not create key.");
        return;
      }
      setNewRawKey(result.rawKey ?? null);
      setKeyName("");
      router.refresh();
    });
  }

  function handleRevoke(id: string) {
    setActionError(null);
    startTransition(async () => {
      const result = await revokeApiKey(id);
      if (!result.ok) {
        setActionError(result.error ?? "Could not revoke key.");
        return;
      }
      router.refresh();
    });
  }

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.refresh();
  }

  async function handleCheckout(tier: "starter" | "pro") {
    setActionError(null);
    setCheckoutPending(tier);
    try {
      const res = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tier })
      });
      const body = (await res.json()) as { url?: string; error?: string };
      if (!res.ok || !body.url) {
        setActionError(body.error ?? "Could not start checkout.");
        setCheckoutPending(null);
        return;
      }
      window.location.href = body.url;
    } catch {
      setActionError("Could not reach the billing service.");
      setCheckoutPending(null);
    }
  }

  async function copyKey() {
    if (!newRawKey) return;
    try {
      await navigator.clipboard.writeText(newRawKey);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Dashboard</h1>
          <p className="text-sm text-ink-soft">{data.email}</p>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="rounded-md border border-surface-border bg-white px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-muted"
        >
          Sign out
        </button>
      </div>

      {actionError ? (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{actionError}</p>
      ) : null}

      {/* Plan + usage */}
      <section className="mt-6 grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-surface-border bg-white p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-soft">
              Current plan
            </h2>
            <TierBadge tier={data.currentTier} />
          </div>
          <p className="mt-3 text-2xl font-bold text-ink">
            {data.requestsThisMonth.toLocaleString()}{" "}
            <span className="text-base font-normal text-ink-soft">
              / {data.quota === null ? "unlimited" : data.quota.toLocaleString()} lookups
            </span>
          </p>
          {data.quota !== null ? (
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface-muted">
              <div
                className="h-full rounded-full bg-brand"
                style={{ width: `${quotaPct}%` }}
              />
            </div>
          ) : null}
          {data.quotaResetAt ? (
            <p className="mt-3 text-xs text-ink-soft">
              Quota resets {new Date(data.quotaResetAt).toLocaleDateString()}.
            </p>
          ) : null}
          <p className="mt-1 text-xs text-ink-soft">
            Billing status: {data.billingActive ? "active subscription" : "no active subscription"}.
          </p>
        </div>

        <div className="rounded-xl border border-surface-border bg-white p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-soft">
            Usage (last 30 days)
          </h2>
          <div className="mt-4">
            <UsageChart data={data.usage} />
          </div>
        </div>
      </section>

      {/* API keys */}
      <section className="mt-6 rounded-xl border border-surface-border bg-white p-6">
        <h2 className="text-lg font-semibold text-ink">API keys</h2>
        <p className="mt-1 text-sm text-ink-soft">
          The raw key is shown only once at creation. Store it somewhere safe.
        </p>

        <form onSubmit={handleCreate} className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex-1">
            <label htmlFor="key-name" className="block text-sm font-medium text-ink">
              Key name
            </label>
            <input
              id="key-name"
              type="text"
              placeholder="Production server"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              className="mt-1 w-full rounded-md border border-surface-border px-3 py-2 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand"
            />
          </div>
          <button
            type="submit"
            disabled={isPending}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-60"
          >
            {isPending ? "Working..." : "Generate key"}
          </button>
        </form>

        {newRawKey ? (
          <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-4">
            <p className="text-sm font-medium text-emerald-800">
              Your new API key (copy it now, it will not be shown again):
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <code className="break-all rounded bg-white px-2 py-1 font-mono text-sm text-ink">
                {newRawKey}
              </code>
              <button
                type="button"
                onClick={copyKey}
                className="rounded-md border border-surface-border bg-white px-3 py-1 text-xs font-medium text-ink hover:bg-surface-muted"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        ) : null}

        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-ink-soft">
                <th className="py-2 pr-4 font-medium">Name</th>
                <th className="py-2 pr-4 font-medium">Prefix</th>
                <th className="py-2 pr-4 font-medium">Tier</th>
                <th className="py-2 pr-4 font-medium">This month</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Created</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {data.keys.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-6 text-center text-ink-soft">
                    No keys yet. Generate one above to start.
                  </td>
                </tr>
              ) : (
                data.keys.map((k) => (
                  <tr key={k.id} className="border-b border-surface-border last:border-0">
                    <td className="py-3 pr-4 text-ink">{k.name ?? "Unnamed"}</td>
                    <td className="py-3 pr-4 font-mono text-xs text-ink-soft">
                      {k.key_prefix}...
                    </td>
                    <td className="py-3 pr-4">
                      <TierBadge tier={k.tier} />
                    </td>
                    <td className="py-3 pr-4 text-ink">
                      {k.requests_this_month.toLocaleString()}
                    </td>
                    <td className="py-3 pr-4">
                      {k.revoked ? (
                        <span className="text-xs font-medium text-red-600">Revoked</span>
                      ) : (
                        <span className="text-xs font-medium text-emerald-600">Active</span>
                      )}
                    </td>
                    <td className="py-3 pr-4 text-ink-soft">
                      {new Date(k.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3 text-right">
                      {!k.revoked ? (
                        <button
                          type="button"
                          onClick={() => handleRevoke(k.id)}
                          disabled={isPending}
                          className="rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-60"
                        >
                          Revoke
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Billing */}
      <section className="mt-6 rounded-xl border border-surface-border bg-white p-6">
        <h2 className="text-lg font-semibold text-ink">Billing</h2>
        <p className="mt-1 text-sm text-ink-soft">
          Upgrade to unlock all 8 cities and higher quotas. Overage is a flat $0.02
          per lookup with no cliff.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {PRICING_TIERS.filter((t) => t.id !== "enterprise").map((tier) => {
            const isCurrent = tier.id === data.currentTier;
            return (
              <div key={tier.id} className="rounded-lg border border-surface-border p-4">
                <div className="flex items-baseline justify-between">
                  <h3 className="font-semibold text-ink">{tier.name}</h3>
                  <span className="text-sm text-ink-soft">
                    {tier.price}
                    {tier.cadence ? ` ${tier.cadence}` : ""}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-soft">
                  {tier.monthlyLookups
                    ? `${tier.monthlyLookups.toLocaleString()} lookups / month`
                    : "Custom volume"}
                </p>
                <div className="mt-3">
                  {isCurrent ? (
                    <span className="inline-block rounded-md bg-surface-muted px-3 py-1.5 text-xs font-medium text-ink-soft">
                      Current plan
                    </span>
                  ) : tier.checkoutTier ? (
                    <button
                      type="button"
                      onClick={() => handleCheckout(tier.checkoutTier!)}
                      disabled={checkoutPending !== null}
                      className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-60"
                    >
                      {checkoutPending === tier.checkoutTier ? "Redirecting..." : `Upgrade to ${tier.name}`}
                    </button>
                  ) : (
                    <span className="inline-block rounded-md bg-surface-muted px-3 py-1.5 text-xs font-medium text-ink-soft">
                      Free tier
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
