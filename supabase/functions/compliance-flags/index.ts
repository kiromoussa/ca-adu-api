// GET /v1/compliance-flags?city=<slug>
//
// Compliance-flag summary per city/zone. Returns one entry per (city, zone)
// with its compliance_flag and validation notes, plus an aggregate count of
// each flag value across the result set. Filter by city slug (optional).
// Requires a valid API key and counts against the caller's monthly quota.

import { getServiceClient } from "../_shared/supabase.ts";
import { authenticate } from "../_shared/auth.ts";
import { writeUsageLog } from "../_shared/log.ts";
import { handlePreflight, jsonResponse } from "../_shared/cors.ts";

const ENDPOINT = "/v1/compliance-flags";

const SELECT =
  "zone_district, compliance_flag, compliance_notes, last_validated_at, " +
  "city:cities!inner(id, name, slug)";

interface FlagRow {
  zone_district: string;
  compliance_flag: string;
  compliance_notes: unknown;
  last_validated_at: string | null;
  city: { id: string; name: string; slug: string } | null;
}

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

  const url = new URL(req.url);
  const city = url.searchParams.get("city")?.trim() || null;

  let query = client.from("adu_rules").select(SELECT);
  if (city) query = query.eq("city.slug", city);
  query = query
    .order("zone_district", { ascending: true });

  const { data, error } = await query;

  if (error) {
    await writeUsageLog(client, {
      apiKeyId: auth.apiKeyId,
      endpoint: ENDPOINT,
      statusCode: 500,
      billable: false,
    });
    return jsonResponse(
      {
        error: "internal_error",
        message: "Failed to load compliance flags.",
      },
      500,
    );
  }

  const rows = (data ?? []) as unknown as FlagRow[];

  // Aggregate counts per compliance_flag value.
  const summary: Record<string, number> = {
    compliant: 0,
    more_restrictive: 0,
    needs_review: 0,
  };
  for (const row of rows) {
    if (row.compliance_flag in summary) {
      summary[row.compliance_flag] += 1;
    } else {
      summary[row.compliance_flag] = 1;
    }
  }

  const entries = rows.map((row) => ({
    city: row.city ? row.city.name : null,
    city_slug: row.city ? row.city.slug : null,
    zone_district: row.zone_district,
    compliance_flag: row.compliance_flag,
    compliance_notes: row.compliance_notes,
    last_validated_at: row.last_validated_at,
  }));

  const cityId = city && rows.length > 0 ? rows[0].city?.id ?? null : null;

  await writeUsageLog(client, {
    apiKeyId: auth.apiKeyId,
    endpoint: ENDPOINT,
    cityId,
    statusCode: 200,
    billable: true,
  });

  return jsonResponse(
    {
      data: entries,
      count: entries.length,
      summary,
      filters: { city },
      tier: auth.tier,
      limit: auth.limit,
      requests_this_month: auth.requestsThisMonth,
    },
    200,
  );
});
