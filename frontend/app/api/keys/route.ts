import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import { generateApiKey } from "@/lib/keys";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// GET /api/keys - list the signed-in user's keys (never returns secrets).
export async function GET() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Not authenticated." }, { status: 401 });
  }

  const { data, error } = await supabase
    .from("api_keys")
    .select(
      "id, name, key_prefix, tier, revoked, requests_this_month, created_at"
    )
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ data: data ?? [] });
}

// POST /api/keys - create a key. Raw value is returned once in the response.
export async function POST(request: NextRequest) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Not authenticated." }, { status: 401 });
  }

  let name = "Default key";
  try {
    const body = (await request.json()) as { name?: string };
    if (typeof body.name === "string" && body.name.trim()) {
      name = body.name.trim().slice(0, 80);
    }
  } catch {
    // Empty or invalid body is fine; fall back to the default name.
  }

  const { raw, hash, prefix } = generateApiKey();
  const service = createServiceClient();
  const { error } = await service.from("api_keys").insert({
    user_id: user.id,
    name,
    key_hash: hash,
    key_prefix: prefix,
    tier: "free"
  });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ key: raw, prefix, name }, { status: 201 });
}
