import "server-only";

import { createHash, randomBytes } from "node:crypto";

export interface GeneratedKey {
  raw: string;
  hash: string;
  prefix: string;
}

// Generate a fresh API key. The raw value is shown to the user exactly once;
// only the sha256 hash and a short display prefix are persisted.
export function generateApiKey(): GeneratedKey {
  const secret = randomBytes(24).toString("hex"); // 48 hex chars
  const raw = `adu_live_${secret}`;
  const hash = hashApiKey(raw);
  const prefix = raw.slice(0, 16); // e.g. adu_live_ab12cd34
  return { raw, hash, prefix };
}

export function hashApiKey(raw: string): string {
  return createHash("sha256").update(raw).digest("hex");
}
