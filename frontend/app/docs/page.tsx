import type { Metadata } from "next";
import SwaggerClient from "./swagger";

export const metadata: Metadata = {
  title: "API docs - CA ADU Zoning API",
  description:
    "Interactive OpenAPI documentation for /v1/adu-rules, /v1/cities, and /v1/compliance-flags."
};

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-ink">API reference</h1>
        <p className="mt-2 max-w-2xl text-ink-soft">
          REST over HTTPS with JSON responses. Authenticate with the{" "}
          <code className="rounded bg-surface-muted px-1 py-0.5 font-mono text-sm">x-api-key</code>{" "}
          header using a key generated in your{" "}
          <a href="/dashboard" className="text-brand hover:text-brand-dark">
            dashboard
          </a>
          . Each call counts against your monthly quota.
        </p>
      </header>
      <div className="rounded-xl border border-surface-border bg-white">
        <SwaggerClient />
      </div>
    </div>
  );
}
