// Usage logging. Every authenticated request (allowed or 429) is written to
// usage_logs so the dashboard can render usage graphs and reconcile billing.
//
// Writes go through the service-role client (usage_logs is service_role-only per
// 0002_rls.sql). Logging failures are swallowed and reported to the function
// console: a logging error must never take down an otherwise-successful request.

import type { SupabaseClient } from "@supabase/supabase-js";

export interface UsageLogEntry {
  apiKeyId: string;
  endpoint: string;
  cityId?: string | null;
  statusCode: number;
  // billable defaults to true for successful (2xx) calls; 429s and errors are
  // logged as non-billable so quota-exceeded requests are not charged.
  billable?: boolean;
}

export async function writeUsageLog(
  client: SupabaseClient,
  entry: UsageLogEntry,
): Promise<void> {
  const billable = entry.billable ??
    (entry.statusCode >= 200 && entry.statusCode < 300);

  try {
    const { error } = await client.from("usage_logs").insert({
      api_key_id: entry.apiKeyId,
      endpoint: entry.endpoint,
      city_id: entry.cityId ?? null,
      status_code: entry.statusCode,
      billable,
    });
    if (error) {
      console.error("usage_logs insert failed:", error.message);
    }
  } catch (err) {
    console.error("usage_logs insert threw:", err);
  }
}
