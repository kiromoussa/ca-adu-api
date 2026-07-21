"use client";

import dynamic from "next/dynamic";
import "swagger-ui-react/swagger-ui.css";

// swagger-ui-react touches window at import time, so load it client-only.
const SwaggerUI = dynamic(() => import("swagger-ui-react"), {
  ssr: false,
  loading: () => (
    <p className="px-6 py-10 text-sm text-ink-soft">Loading interactive docs...</p>
  )
});

export default function SwaggerClient() {
  // The spec is served as a static asset from /public.
  return <SwaggerUI url="/openapi.yaml" docExpansion="list" />;
}
