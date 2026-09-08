import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// .mts so Vite loads this as ESM. package.json has no "type": "module", so a
// .ts config here is loaded as CommonJS and warns on the import syntax below.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Vite does not read tsconfig "paths"; this mirrors "@/*" -> "./*".
    alias: {
      "@": path.resolve(import.meta.dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    // Pinned so relative MSW handler paths ("/api/...") have a stable origin to
    // resolve against, and so tests never depend on a jsdom default changing.
    environmentOptions: {
      jsdom: { url: "http://localhost:3000" },
    },
    globals: true,
    setupFiles: ["./test-utils/setup.ts"],
    include: ["**/*.test.ts", "**/*.test.tsx"],
    // tests/ is Playwright's testDir. Both suites use describe/it, so without
    // this exclude Vitest would try to run the 24 E2E specs.
    exclude: [
      "**/node_modules/**",
      "**/.next*/**",
      "tests/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
});
