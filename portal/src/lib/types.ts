// Shared types for config-driven portal content. These mirror the shape of
// the repo-level config/*.yaml files (config/jurisdictions.yaml,
// config/plans.yaml, config/sources.yaml) - the single source of truth for
// coverage and pricing claims. Do not hardcode values these types describe.

export type CoverageStatus = "planned" | "ingesting" | "production";

export type PublisherType = "american_legal" | "municode";

export interface Jurisdiction {
  slug: string;
  name: string;
  display_name: string;
  state: string;
  county: string;
  publisher_type: PublisherType;
  official_code_url: string;
  coverage_status: CoverageStatus;
  source_keys: string[];
  supported_project_types: string[];
  notes: string;
}

export interface JurisdictionsConfig {
  version: number;
  project_types: string[];
  jurisdictions: Jurisdiction[];
}

export interface SourceRegistryEntry {
  key: string;
  name: string;
  publisher: string;
  source_type: string;
  authority_rank: number;
  jurisdiction_slug?: string;
  base_url: string;
  rest_service_url?: string | null;
  retrieval: string;
  license_or_terms_notes: string;
}

export interface SourcesConfig {
  version: number;
  sources: SourceRegistryEntry[];
}

export type PlanKey = "BASIC" | "PRO" | "ULTRA" | "MEGA";

export interface PlanFeatures {
  feasibility_analysis: boolean;
  jurisdiction_rules: boolean;
  changelog: boolean;
  shareable_analysis_token: boolean;
  priority_support: boolean;
  [key: string]: boolean;
}

export interface Plan {
  display_name: string;
  price_usd: number;
  billing_period: string;
  monthly_quota: number;
  hard_cap: boolean;
  rate_limit_per_minute: number;
  overages_allowed: boolean;
  rapidapi_plan_slug: string;
  description: string;
  features: PlanFeatures;
}

export interface BillableUnit {
  name: string;
  description: string;
  billed_endpoints: string[];
  meter_on: string[];
  do_not_meter: string[];
  non_billable_endpoints: string[];
}

export interface PlansConfig {
  version: number;
  currency: string;
  billing: {
    billable_unit: BillableUnit;
    dedupe: {
      window_hours: number;
      fingerprint_fields: string[];
      cache_hit_billed: boolean;
      idempotency: {
        header: string;
        window_hours: number;
        conflict_status: number;
      };
    };
    overages: {
      enabled: boolean;
      on_quota_exceeded: {
        http_status: number;
        error_code: string;
      };
    };
  };
  metering: {
    primary: string;
    fallback: string;
    reset: string;
    usage_table: string;
    burst_limiter: {
      enabled: boolean;
      default_requests_per_minute: number;
    };
  };
  plans: Record<PlanKey, Plan>;
}

export interface ChangelogEntry {
  id?: string;
  jurisdiction_slug?: string | null;
  jurisdiction_name?: string | null;
  title?: string;
  summary?: string;
  description?: string;
  category?: string;
  published_at?: string;
  created_at?: string;
}
