import type { Metadata } from "next";

import SwaggerViewer from "./SwaggerViewer";

export const metadata: Metadata = {
  title: "API Docs",
  description: "OpenAPI 3.1 reference for the ADU Atlas API.",
};

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-content px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">API reference</h1>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
        Spec-first, OpenAPI 3.1. Every request and response schema below
        matches the Pydantic models enforced on the server: strict field
        types, an explicit feasibility_status enum, and provenance on every
        substantive field. Authenticate with X-RapidAPI-Key and
        X-RapidAPI-Host when calling through RapidAPI, or with x-api-key for
        a direct integration.
      </p>
      <div className="mt-10">
        <SwaggerViewer />
      </div>
    </div>
  );
}
