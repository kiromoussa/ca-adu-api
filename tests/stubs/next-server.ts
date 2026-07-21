// Minimal stand-in for "next/server" so the Stripe webhook route handler can be
// imported and driven under Vitest without pulling in the full Next.js runtime.
// Only the surface the route uses (NextResponse.json + the NextRequest type) is
// provided.

export class NextResponse {
  static json(body: unknown, init?: { status?: number }): {
    status: number;
    body: unknown;
    json: () => Promise<unknown>;
  } {
    const status = init?.status ?? 200;
    return {
      status,
      body,
      json: async () => body,
    };
  }
}

// The route imports NextRequest as a type only, so an alias is enough.
export type NextRequest = Request;
