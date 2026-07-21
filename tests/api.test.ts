// Integration tests for the edge-function auth + quota layer
// (supabase/functions/_shared/auth.ts), which every /v1 endpoint delegates to.
//
// Asserts the two failure modes the API contract promises:
//   - 401 on a missing / invalid / revoked key
//   - 429 when a valid key is over its monthly quota
// plus the happy path. The Supabase client and the increment_api_usage RPC are
// mocked, so there is no network and no real database.

import { describe, it, expect } from "vitest";
import {
  authenticate,
  extractApiKey,
  sha256Hex,
  TIER_LIMITS,
} from "../supabase/functions/_shared/auth.ts";

// A fake SupabaseClient matching the exact call chain in authenticate():
//   client.from("api_keys").select(...).eq(...).eq(...).maybeSingle()
//   client.rpc("increment_api_usage", { p_key_hash })
function makeClient(opts: {
  keyRow?: Record<string, unknown> | null;
  keyErr?: unknown;
  rpcData?: unknown;
  rpcErr?: unknown;
}) {
  const builder = {
    select() {
      return builder;
    },
    eq() {
      return builder;
    },
    maybeSingle() {
      return Promise.resolve({
        data: opts.keyRow ?? null,
        error: opts.keyErr ?? null,
      });
    },
  };
  return {
    from(_table: string) {
      return builder;
    },
    rpc(_name: string, _params: Record<string, unknown>) {
      return Promise.resolve({
        data: opts.rpcData ?? null,
        error: opts.rpcErr ?? null,
      });
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

function request(headers: Record<string, string>): Request {
  return new Request("https://api.example.com/v1/adu-rules", { headers });
}

describe("extractApiKey", () => {
  it("reads a bearer token", () => {
    expect(extractApiKey(request({ authorization: "Bearer abc123" }))).toBe("abc123");
  });

  it("reads the x-api-key header", () => {
    expect(extractApiKey(request({ "x-api-key": "xyz789" }))).toBe("xyz789");
  });

  it("returns null when no key is present", () => {
    expect(extractApiKey(request({}))).toBeNull();
  });
});

describe("sha256Hex", () => {
  it("produces the known SHA-256 digest of the empty string", async () => {
    expect(await sha256Hex("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });
});

describe("authenticate", () => {
  it("returns 401 when the key is missing", async () => {
    const client = makeClient({});
    const result = await authenticate(client, request({}));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.status).toBe(401);
    expect(result.apiKeyId).toBeNull();
    expect(result.body.error).toBe("unauthorized");
  });

  it("returns 401 when the key is unknown or revoked", async () => {
    const client = makeClient({ keyRow: null });
    const result = await authenticate(client, request({ authorization: "Bearer bad-key" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.status).toBe(401);
    expect(result.apiKeyId).toBeNull();
  });

  it("returns 401 when the key lookup errors", async () => {
    const client = makeClient({ keyErr: { message: "boom" } });
    const result = await authenticate(client, request({ "x-api-key": "some-key" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.status).toBe(401);
  });

  it("returns 429 when a valid key is over quota", async () => {
    const client = makeClient({
      keyRow: { id: "key-1", tier: "free", revoked: false },
      rpcData: [{ allowed: false, tier: "free", requests_this_month: 50 }],
    });
    const result = await authenticate(client, request({ authorization: "Bearer good-key" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.status).toBe(429);
    // The 429 is still attributed to the real key id so usage can be logged.
    expect(result.apiKeyId).toBe("key-1");
    expect(result.body.error).toBe("quota_exceeded");
    expect(result.body.tier).toBe("free");
    expect(result.body.limit).toBe(TIER_LIMITS.free);
    expect(result.body.requests_this_month).toBe(50);
  });

  it("allows a valid key that is under quota", async () => {
    const client = makeClient({
      keyRow: { id: "key-2", tier: "starter", revoked: false },
      rpcData: [{ allowed: true, tier: "starter", requests_this_month: 12 }],
    });
    const result = await authenticate(client, request({ authorization: "Bearer good-key" }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.apiKeyId).toBe("key-2");
    expect(result.tier).toBe("starter");
    expect(result.limit).toBe(TIER_LIMITS.starter);
    expect(result.requestsThisMonth).toBe(12);
  });

  it("returns 401 when the RPC reports an unknown key (allowed=false, no tier)", async () => {
    const client = makeClient({
      keyRow: { id: "key-3", tier: "free", revoked: false },
      rpcData: [{ allowed: false, tier: null, requests_this_month: 0 }],
    });
    const result = await authenticate(client, request({ authorization: "Bearer good-key" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.status).toBe(401);
  });

  it("returns 401 when the usage RPC errors", async () => {
    const client = makeClient({
      keyRow: { id: "key-4", tier: "pro", revoked: false },
      rpcErr: { message: "rpc failed" },
    });
    const result = await authenticate(client, request({ authorization: "Bearer good-key" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.status).toBe(401);
    expect(result.apiKeyId).toBe("key-4");
  });
});
