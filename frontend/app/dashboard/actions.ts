"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import { generateApiKey } from "@/lib/keys";

export interface CreateKeyResult {
  ok: boolean;
  error?: string;
  // Raw key is returned exactly once, on creation.
  rawKey?: string;
  prefix?: string;
}

export interface ActionResult {
  ok: boolean;
  error?: string;
}

// Create a new API key for the signed-in user. The write uses the service-role
// client, but only after the caller's identity is verified via the session, and
// user_id is taken from that verified session (never from client input).
export async function createApiKey(name: string): Promise<CreateKeyResult> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return { ok: false, error: "Not authenticated." };
  }

  const trimmed = (name || "").trim().slice(0, 80);
  const { raw, hash, prefix } = generateApiKey();

  const service = createServiceClient();
  const { error } = await service.from("api_keys").insert({
    user_id: user.id,
    name: trimmed || "Default key",
    key_hash: hash,
    key_prefix: prefix,
    tier: "free"
  });

  if (error) {
    return { ok: false, error: error.message };
  }

  revalidatePath("/dashboard");
  return { ok: true, rawKey: raw, prefix };
}

// Revoke a key. Scoped to the caller's own user_id so one user can never revoke
// another user's key even though the write goes through the service role.
export async function revokeApiKey(keyId: string): Promise<ActionResult> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return { ok: false, error: "Not authenticated." };
  }

  const service = createServiceClient();
  const { error } = await service
    .from("api_keys")
    .update({ revoked: true })
    .eq("id", keyId)
    .eq("user_id", user.id);

  if (error) {
    return { ok: false, error: error.message };
  }

  revalidatePath("/dashboard");
  return { ok: true };
}

export async function signOut(): Promise<void> {
  const supabase = createClient();
  await supabase.auth.signOut();
  redirect("/dashboard");
}
