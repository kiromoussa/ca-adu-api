// Shared CORS headers for all Edge Functions.
// The API is a public developer API, so we allow any origin. Auth is enforced
// per-request via the API key, not via origin, so a permissive CORS policy is fine.

export const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers":
    "authorization, x-api-key, x-client-info, apikey, content-type",
  "Access-Control-Max-Age": "86400",
};

// JSON response helper that always includes CORS + content-type headers.
export function jsonResponse(
  body: unknown,
  status = 200,
  extraHeaders: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json; charset=utf-8",
      ...extraHeaders,
    },
  });
}

// Preflight handler. Returns a Response for OPTIONS, or null otherwise.
export function handlePreflight(req: Request): Response | null {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  return null;
}
