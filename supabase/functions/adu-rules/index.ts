// GET /v1/adu-rules?city=<slug>&zone=<zone_district>
//
// Returns state-law-validated ADU rule rows joined to their city. Filter by city
// slug (e.g. los_angeles) and optionally by zone_district (e.g. R-1). Requires a
// valid API key and counts against the caller's monthly quota.

import { getServiceClient } from "../_shared/supabase.ts";
import { authenticate } from "../_shared/auth.ts";
import { writeUsageLog } from "../_shared/log.ts";
import { handlePreflight, jsonResponse } from "../_shared/cors.ts";

const ENDPOINT = "/v1/adu-rules";

// Every adu_rules column, spelled out so the response shape is explicit and
// stable regardless of future column additions.
const ADU_RULES_COLUMNS = [
  "id",
  "zone_district",
  "max_height_detached_standard_ft",
  "max_height_near_transit_ft",
  "max_height_multifamily_lot_ft",
  "max_height_attached_ft",
  "side_rear_setback_min_ft",
  "front_setback_restriction",
  "owner_occupancy_required_adu",
  "owner_occupancy_required_jadu",
  "jadu_allowed",
  "jadu_separate_sale_allowed",
  "adu_condo_sale_allowed",
  "parking_required",
  "demolition_permit_concurrent",
  "permit_review_days",
  "fire_sprinkler_trigger",
  "impact_fee_exempt_sqft_threshold",
  "max_size_sqft_1br",
  "max_size_sqft_2br",
  "max_size_sqft_general_cap",
  "nonconforming_zoning_denial_allowed",
  "pre_2018_unpermitted_adu_amnesty",
  "sb9_duplex_ministerial",
  "sb9_lot_split_min_lot_sqft",
  "sb9_lot_split_ratio",
  "sb9_one_split_per_owner",
  "source_section_id",
  "compliance_flag",
  "compliance_notes",
  "last_validated_at",
  "created_at",
].join(", ");

const SELECT = `${ADU_RULES_COLUMNS}, city:cities!inner(id, name, slug, publisher_type, base_url, last_scraped_at)`;

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
  const zone = url.searchParams.get("zone")?.trim() || null;

  let query = client.from("adu_rules").select(SELECT);

  if (city) query = query.eq("city.slug", city);
  if (zone) query = query.ilike("zone_district", zone);

  query = query.order("zone_district", { ascending: true });

  const { data, error } = await query;

  if (error) {
    await writeUsageLog(client, {
      apiKeyId: auth.apiKeyId,
      endpoint: ENDPOINT,
      statusCode: 500,
      billable: false,
    });
    return jsonResponse(
      { error: "internal_error", message: "Failed to load ADU rules." },
      500,
    );
  }

  const rows = data ?? [];
  // Attribute the log to a single city when the caller filtered by one.
  const cityId = city && rows.length > 0
    ? ((rows[0] as unknown as Record<string, unknown>).city as { id?: string } | null)?.id ?? null
    : null;

  await writeUsageLog(client, {
    apiKeyId: auth.apiKeyId,
    endpoint: ENDPOINT,
    cityId,
    statusCode: 200,
    billable: true,
  });

  return jsonResponse(
    {
      data: rows,
      count: rows.length,
      filters: { city, zone },
      tier: auth.tier,
      limit: auth.limit,
      requests_this_month: auth.requestsThisMonth,
    },
    200,
  );
});
