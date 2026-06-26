import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    testTimeout: 120000, // 120 second timeout for integration tests
    hookTimeout: 60000,
  },
});
