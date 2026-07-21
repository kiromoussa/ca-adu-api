"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import "swagger-ui-react/swagger-ui.css";

const SwaggerUI = dynamic(() => import("swagger-ui-react"), { ssr: false });

const FALLBACK_SPEC_URL = "/openapi.yaml";
const LIVE_CHECK_TIMEOUT_MS = 4000;

function buildPrimarySpecUrl(): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "");
  return base ? `${base}/openapi.json` : null;
}

type SpecSource = "checking" | "live" | "bundled";

export default function SwaggerViewer() {
  const [specUrl, setSpecUrl] = useState<string>(FALLBACK_SPEC_URL);
  const [source, setSource] = useState<SpecSource>("checking");

  useEffect(() => {
    let cancelled = false;
    const primary = buildPrimarySpecUrl();

    if (!primary) {
      setSource("bundled");
      return;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), LIVE_CHECK_TIMEOUT_MS);

    fetch(primary, { signal: controller.signal, cache: "no-store" })
      .then((res) => {
        if (cancelled) return;
        if (res.ok) {
          setSpecUrl(primary);
          setSource("live");
        } else {
          setSource("bundled");
        }
      })
      .catch(() => {
        if (!cancelled) setSource("bundled");
      })
      .finally(() => {
        clearTimeout(timeout);
      });

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timeout);
    };
  }, []);

  return (
    <div>
      <div className="mb-4 rounded-md border border-ink/10 bg-ink/[0.03] px-4 py-2 text-sm text-ink/70 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-dark/70">
        {source === "checking" &&
          "Checking for a live specification from the configured API..."}
        {source === "live" &&
          "Showing the live specification served by the API at /openapi.json."}
        {source === "bundled" &&
          "Showing the bundled specification snapshot. Set NEXT_PUBLIC_API_BASE_URL to load the live spec from the API instead."}
      </div>
      <div className="swagger-portal-wrapper rounded-lg border border-ink/10 bg-white dark:border-white/10">
        <SwaggerUI
          url={specUrl}
          docExpansion="list"
          defaultModelsExpandDepth={-1}
          tryItOutEnabled
        />
      </div>
    </div>
  );
}
