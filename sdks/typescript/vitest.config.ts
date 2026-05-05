import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    testTimeout: 120000, // Streaming and RAG tests can take longer in CI.
    hookTimeout: 120000,
  },
});
