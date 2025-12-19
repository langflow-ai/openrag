import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    testTimeout: 60000, // 60 second timeout for integration tests
    hookTimeout: 60000,
  },
});
