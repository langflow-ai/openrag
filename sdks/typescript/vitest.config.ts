import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    testTimeout: 60000, // 60 second timeout for integration tests
    hookTimeout: 60000,
    // Retry only the failing tests (transient infra/index-refresh latency)
    // rather than re-running the whole suite.
    retry: 2,
  },
});
