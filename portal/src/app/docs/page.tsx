import type { Metadata } from "next";

import SwaggerViewer from "./SwaggerViewer";

export const metadata: Metadata = {
  title: "API Docs",
  description: "OpenAPI 3.1 reference for the ADU Atlas API.",
};

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-content px-6 py-16">
      <p className="eyebrow">Reference</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tightest sm:text-4xl">
        API reference
      </h1>
      <p className="mt-4 max-w-measure leading-relaxed text-muted">
        Spec-first, OpenAPI 3.1. Every request and response schema below matches
        the Pydantic models enforced on the server: strict field types, an
        explicit feasibility_status enum, and provenance on every substantive
        field. Authenticate with X-RapidAPI-Key and X-RapidAPI-Host through
        RapidAPI, or with x-api-key for a direct integration.
      </p>
      <div className="mt-10 rounded-card border border-line bg-surface-2 p-2 sm:p-4">
        <SwaggerViewer />
      </div>
    </div>
  );
}
