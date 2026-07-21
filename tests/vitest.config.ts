import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Resolve "@" to the frontend package root so the webhook route's "@/lib/..."
// imports resolve (they are then replaced by vi.mock in the tests). "next/server"
// and "server-only" are aliased to local stubs so no Next.js/Node-only runtime is
// required.
const frontendRoot = fileURLToPath(new URL("../frontend", import.meta.url)).replace(/\/$/, "");

export default defineConfig({
  test: {
    environment: "node",
    include: ["*.test.ts"],
  },
  resolve: {
    alias: {
      "@": frontendRoot,
      "next/server": fileURLToPath(new URL("./stubs/next-server.ts", import.meta.url)),
      "server-only": fileURLToPath(new URL("./stubs/empty.ts", import.meta.url)),
    },
  },
});
