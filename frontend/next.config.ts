import dotenv from "dotenv";
import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";
import path from "path";

// Keep this config self-contained: next start evaluates next.config.ts from
// the production image, where application source files under lib/ are not
// copied. The browser-side client has the same normalization in
// lib/frontend-base-path.ts.
function normalizeFrontendBasePath(value?: string): string {
  const trimmed = value?.trim();
  if (!trimmed || trimmed === "/") return "";

  const prefixed = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const normalized = prefixed.replace(/\/+$/, "");

  if (
    !normalized ||
    !/^[A-Za-z0-9/._~-]+$/.test(normalized) ||
    normalized.includes("//") ||
    /\/\.{1,2}(\/|$)/.test(normalized)
  ) {
    throw new Error(
      "OPENRAG_FRONTEND_BASE_PATH must be a path such as /openrag-fe",
    );
  }

  return normalized;
}

// Load environment variables from the root env file. Honors ENV_FILE (set by
// the Makefile) so per-instance env files like `.env.instance2` are respected;
// defaults to `.env`. Absolute ENV_FILE paths are used as-is.
dotenv.config({
  path: path.resolve(process.cwd(), "..", process.env.ENV_FILE || ".env"),
});

// Next inlines `basePath` into browser bundles. Image builds use a placeholder
// that the entrypoint replaces in a writable runtime copy of the assets.
const RUNTIME_BASE_PATH_PLACEHOLDER =
  "/NEXT_PUBLIC_BASE_PATH_PLACEHOLDER_a1b2c3d4";

function getAllowedDevOrigins(): string[] {
  const allowedDevOrigins = process.env.NEXT_ALLOWED_DEV_ORIGINS;

  if (!allowedDevOrigins) {
    // Only the server's own hostname is allowed.
    // No additional origins.
    // Explicitly setting an empty array is equivalent to not setting it.
    return [];
  }

  return allowedDevOrigins
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
}

const createNextConfig = (phase: string): NextConfig => {
  const useRuntimeBasePathPlaceholder =
    process.env.OPENRAG_FRONTEND_RUNTIME_BASE_PATH === "true";
  const frontendBasePath =
    phase !== PHASE_DEVELOPMENT_SERVER && useRuntimeBasePathPlaceholder
      ? RUNTIME_BASE_PATH_PLACEHOLDER
      : normalizeFrontendBasePath(process.env.OPENRAG_FRONTEND_BASE_PATH);

  return {
    // `basePath` is compiled into the browser bundle. The same value is exposed
    // below so the Axios API client calls /<basePath>/api rather than /api.
    basePath: frontendBasePath,
    env: {
      NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH: frontendBasePath,
    },
    output: "standalone",
    // Build/dev output directory. Overridable via NEXT_DIST_DIR so multiple
    // `next dev` servers can run simultaneously from this same directory: Next.js
    // 16 acquires a lock at `<distDir>/lock` keyed on the project dir + distDir
    // (not the port), so a second instance must use a distinct distDir.
    distDir: process.env.NEXT_DIST_DIR || ".next",
    // Increase timeout for API routes
    experimental: {
      proxyTimeout: 300000, // 5 minutes
    },
    async rewrites() {
      return [{ source: "/mcp/:path*", destination: "/api/mcp/:path*" }];
    },
    // Disable built-in image optimization so Next does not require the `sharp`
    // native dependency (and its LGPL libvips binaries). The only <Image> usage
    // is a 32px file-preview thumbnail, which does not benefit from optimization.
    images: {
      unoptimized: true,
    },
    // Ignore TypeScript errors during build
    typescript: {
      ignoreBuildErrors: true,
    },
    // Allow cross-origin requests in development
    allowedDevOrigins: getAllowedDevOrigins(),
  };
};

export default createNextConfig;
