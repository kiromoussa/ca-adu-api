// GET /v1/cities
// Lists the cities covered by the API. Requires a valid API key and counts
// against the caller's monthly quota.

import { getServiceClient } from "../_shared/supabase.ts";
import { authenticate } from "../_shared/auth.ts";
import { writeUsageLog } from "../_shared/log.ts";
import { handlePreflight, jsonResponse } from "../_shared/cors.ts";

const ENDPOINT = "/v1/cities";

Deno.serve(async (req: Request): Promise<Response> => {
  const preflight = handlePreflight(req);
  if (preflight) return preflight;

  if (req.method !== "GET") {
    return jsonResponse(
      { error: "method_not_allowed", message: "Use GET." },
      405,
      { Allow: "GET, OPTIONS" },
    );
  }

  const client = getServiceClient();

  const auth = await authenticate(client, req);
  if (!auth.ok) {
    if (auth.apiKeyId) {
      await writeUsageLog(client, {
        apiKeyId: auth.apiKeyId,
        endpoint: ENDPOINT,
        statusCode: auth.status,
        billable: false,
      });
    }
    return jsonResponse(auth.body, auth.status);
  }

  const { data, error } = await client
    .from("cities")
    .select(
      "id, name, slug, publisher_type, base_url, last_scraped_at, created_at",
    )
    .order("name", { ascending: true });

  if (error) {
    await writeUsageLog(client, {
      apiKeyId: auth.apiKeyId,
      endpoint: ENDPOINT,
      statusCode: 500,
      billable: false,
    });
    return jsonResponse(
      { error: "internal_error", message: "Failed to load cities." },
      500,
    );
  }

  await writeUsageLog(client, {
    apiKeyId: auth.apiKeyId,
    endpoint: ENDPOINT,
    statusCode: 200,
    billable: true,
  });

  return jsonResponse(
    {
      data: data ?? [],
      count: data?.length ?? 0,
      tier: auth.tier,
      limit: auth.limit,
      requests_this_month: auth.requestsThisMonth,
    },
    200,
  );
});
