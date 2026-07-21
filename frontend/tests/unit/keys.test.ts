import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { generateApiKey, hashApiKey } from "@/lib/keys";

describe("generateApiKey", () => {
  it("produces a live-prefixed raw key", () => {
    const { raw } = generateApiKey();
    expect(raw.startsWith("adu_live_")).toBe(true);
    expect(raw.length).toBeGreaterThan(20);
  });

  it("stores only a sha256 hash and a short display prefix", () => {
    const { raw, hash, prefix } = generateApiKey();
    expect(hash).toBe(createHash("sha256").update(raw).digest("hex"));
    expect(hash).toHaveLength(64);
    expect(raw.startsWith(prefix)).toBe(true);
    expect(prefix).toHaveLength(16);
    // The prefix must never reveal the full secret.
    expect(prefix.length).toBeLessThan(raw.length);
  });

  it("generates unique keys", () => {
    const a = generateApiKey();
    const b = generateApiKey();
    expect(a.raw).not.toBe(b.raw);
    expect(a.hash).not.toBe(b.hash);
  });
});

describe("hashApiKey", () => {
  it("is deterministic", () => {
    const raw = "adu_live_deadbeef";
    expect(hashApiKey(raw)).toBe(hashApiKey(raw));
    expect(hashApiKey(raw)).toBe(createHash("sha256").update(raw).digest("hex"));
  });
});
