import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL(".", import.meta.url)).replace(/\/$/, "");

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/unit/**/*.test.ts"]
  },
  resolve: {
    alias: {
      "@": projectRoot,
      "server-only": fileURLToPath(new URL("./tests/stubs/empty.ts", import.meta.url))
    }
  }
});
