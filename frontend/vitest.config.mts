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
    coverage: {
      provider: "v8",
      // "lcov" emits DA records, which scripts/check-diff-coverage.mjs uses for
      // per-line hit counts (including executable multiline continuations).
      reporter: ["text", "json", "json-summary", "html", "lcov"],
      reportsDirectory: "coverage",
      // `include` is what makes the number honest: without it, coverage is
      // reported only for files some test already imports, which reads as a
      // high percentage of a tiny denominator.
      include: [
        "app/**/*.{ts,tsx}",
        "components/**/*.{ts,tsx}",
        "contexts/**/*.{ts,tsx}",
        "hooks/**/*.{ts,tsx}",
        "lib/**/*.{ts,tsx}",
        "enhancements/**/*.{ts,tsx}",
      ],
      exclude: [
        "**/*.test.{ts,tsx}",
        "**/*.d.ts",
        // Next.js route/layout plumbing, not logic worth a coverage target.
        "app/**/layout.tsx",
        "app/**/error.tsx",
        "app/**/global-error.tsx",
        "app/**/loading.tsx",
        "app/**/route.ts",
      ],
    },
  },
});
