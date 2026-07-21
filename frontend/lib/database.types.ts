// Hand-authored mirror of the Supabase schema (supabase/migrations/0001_initial_schema.sql).
// Replaced by `npm run gen:types` once the local stack is linked. Keep field names and
// enum values in sync with the migration.
//
// Every table carries a `Relationships: []` key: postgrest-js's GenericTable type
// requires it, and omitting it makes the schema fail the GenericSchema constraint,
// which collapses all `.from(...)` results to `never`. `supabase gen types` populates
// it with the real foreign keys; an empty array is sufficient for type resolution.

export type PublisherType = "alp" | "municode";
export type ComplianceFlag = "compliant" | "more_restrictive" | "needs_review";
export type ApiTier = "free" | "starter" | "pro" | "enterprise";

export interface Database {
  public: {
    Tables: {
      cities: {
        Row: {
          id: string;
          name: string;
          slug: string;
          publisher_type: PublisherType;
          base_url: string;
          last_scraped_at: string | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          name: string;
          slug: string;
          publisher_type: PublisherType;
          base_url: string;
          last_scraped_at?: string | null;
          created_at?: string;
        };
        Update: {
          id?: string;
          name?: string;
          slug?: string;
          publisher_type?: PublisherType;
          base_url?: string;
          last_scraped_at?: string | null;
          created_at?: string;
        };
        Relationships: [];
      };
      zoning_sections: {
        Row: {
          id: string;
          city_id: string;
          title_number: string | null;
          chapter_number: string | null;
          section_number: string | null;
          section_url: string;
          raw_text: string | null;
          content_hash: string | null;
          last_updated: string;
          created_at: string;
        };
        Insert: {
          id?: string;
          city_id: string;
          title_number?: string | null;
          chapter_number?: string | null;
          section_number?: string | null;
          section_url: string;
          raw_text?: string | null;
          content_hash?: string | null;
          last_updated?: string;
          created_at?: string;
        };
        Update: {
          id?: string;
          city_id?: string;
          title_number?: string | null;
          chapter_number?: string | null;
          section_number?: string | null;
          section_url?: string;
          raw_text?: string | null;
          content_hash?: string | null;
          last_updated?: string;
          created_at?: string;
        };
        Relationships: [];
      };
      adu_rules: {
        Row: {
          id: string;
          city_id: string;
          zone_district: string;
          max_height_detached_standard_ft: number | null;
          max_height_near_transit_ft: number | null;
          max_height_multifamily_lot_ft: number | null;
          max_height_attached_ft: number | null;
          side_rear_setback_min_ft: number | null;
          front_setback_restriction: boolean | null;
          owner_occupancy_required_adu: boolean | null;
          owner_occupancy_required_jadu: boolean | null;
          jadu_allowed: boolean | null;
          jadu_separate_sale_allowed: boolean | null;
          adu_condo_sale_allowed: boolean | null;
          parking_required: boolean | null;
          demolition_permit_concurrent: boolean | null;
          permit_review_days: number | null;
          fire_sprinkler_trigger: boolean | null;
          impact_fee_exempt_sqft_threshold: number | null;
          max_size_sqft_1br: number | null;
          max_size_sqft_2br: number | null;
          max_size_sqft_general_cap: number | null;
          nonconforming_zoning_denial_allowed: boolean | null;
          pre_2018_unpermitted_adu_amnesty: boolean | null;
          sb9_duplex_ministerial: boolean | null;
          sb9_lot_split_min_lot_sqft: number | null;
          sb9_lot_split_ratio: number | null;
          sb9_one_split_per_owner: boolean | null;
          source_section_id: string | null;
          compliance_flag: ComplianceFlag;
          compliance_notes: Record<string, unknown> | null;
          last_validated_at: string | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          city_id: string;
          zone_district: string;
          max_height_detached_standard_ft?: number | null;
          max_height_near_transit_ft?: number | null;
          max_height_multifamily_lot_ft?: number | null;
          max_height_attached_ft?: number | null;
          side_rear_setback_min_ft?: number | null;
          front_setback_restriction?: boolean | null;
          owner_occupancy_required_adu?: boolean | null;
          owner_occupancy_required_jadu?: boolean | null;
          jadu_allowed?: boolean | null;
          jadu_separate_sale_allowed?: boolean | null;
          adu_condo_sale_allowed?: boolean | null;
          parking_required?: boolean | null;
          demolition_permit_concurrent?: boolean | null;
          permit_review_days?: number | null;
          fire_sprinkler_trigger?: boolean | null;
          impact_fee_exempt_sqft_threshold?: number | null;
          max_size_sqft_1br?: number | null;
          max_size_sqft_2br?: number | null;
          max_size_sqft_general_cap?: number | null;
          nonconforming_zoning_denial_allowed?: boolean | null;
          pre_2018_unpermitted_adu_amnesty?: boolean | null;
          sb9_duplex_ministerial?: boolean | null;
          sb9_lot_split_min_lot_sqft?: number | null;
          sb9_lot_split_ratio?: number | null;
          sb9_one_split_per_owner?: boolean | null;
          source_section_id?: string | null;
          compliance_flag?: ComplianceFlag;
          compliance_notes?: Record<string, unknown> | null;
          last_validated_at?: string | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["adu_rules"]["Insert"]>;
        Relationships: [];
      };
      api_keys: {
        Row: {
          id: string;
          user_id: string;
          name: string | null;
          key_hash: string;
          key_prefix: string;
          tier: ApiTier;
          requests_this_month: number;
          quota_reset_at: string;
          stripe_customer_id: string | null;
          stripe_subscription_id: string | null;
          revoked: boolean;
          created_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          name?: string | null;
          key_hash: string;
          key_prefix: string;
          tier?: ApiTier;
          requests_this_month?: number;
          quota_reset_at?: string;
          stripe_customer_id?: string | null;
          stripe_subscription_id?: string | null;
          revoked?: boolean;
          created_at?: string;
        };
        Update: {
          id?: string;
          user_id?: string;
          name?: string | null;
          key_hash?: string;
          key_prefix?: string;
          tier?: ApiTier;
          requests_this_month?: number;
          quota_reset_at?: string;
          stripe_customer_id?: string | null;
          stripe_subscription_id?: string | null;
          revoked?: boolean;
          created_at?: string;
        };
        Relationships: [];
      };
      usage_logs: {
        Row: {
          id: string;
          api_key_id: string;
          endpoint: string;
          city_id: string | null;
          status_code: number | null;
          billable: boolean;
          created_at: string;
        };
        Insert: {
          id?: string;
          api_key_id: string;
          endpoint: string;
          city_id?: string | null;
          status_code?: number | null;
          billable?: boolean;
          created_at?: string;
        };
        Update: {
          id?: string;
          api_key_id?: string;
          endpoint?: string;
          city_id?: string | null;
          status_code?: number | null;
          billable?: boolean;
          created_at?: string;
        };
        Relationships: [];
      };
      qa_alerts: {
        Row: {
          id: string;
          city_id: string | null;
          source: string;
          field: string | null;
          scraped_value: string | null;
          hcd_finding: string | null;
          severity: string;
          resolved: boolean;
          created_at: string;
        };
        Insert: {
          id?: string;
          city_id?: string | null;
          source: string;
          field?: string | null;
          scraped_value?: string | null;
          hcd_finding?: string | null;
          severity?: string;
          resolved?: boolean;
          created_at?: string;
        };
        Update: {
          id?: string;
          city_id?: string | null;
          source?: string;
          field?: string | null;
          scraped_value?: string | null;
          hcd_finding?: string | null;
          severity?: string;
          resolved?: boolean;
          created_at?: string;
        };
        Relationships: [];
      };
    };
    Views: {
      [_ in never]: never;
    };
    Functions: {
      increment_api_usage: {
        Args: { p_key_hash: string };
        Returns: {
          allowed: boolean;
          tier: ApiTier;
          requests_this_month: number;
        }[];
      };
    };
    Enums: {
      publisher_type: PublisherType;
      compliance_flag: ComplianceFlag;
      api_tier: ApiTier;
    };
    CompositeTypes: {
      [_ in never]: never;
    };
  };
}
