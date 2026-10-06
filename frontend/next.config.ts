import dotenv from "dotenv";
import type { NextConfig } from "next";
import path from "path";
import { normalizeFrontendBasePath } from "./lib/frontend-base-path";

// Load environment variables from the root env file. Honors ENV_FILE (set by
// the Makefile) so per-instance env files like `.env.instance2` are respected;
// defaults to `.env`. Absolute ENV_FILE paths are used as-is.
dotenv.config({
  path: path.resolve(process.cwd(), "..", process.env.ENV_FILE || ".env"),
});

const frontendBasePath = normalizeFrontendBasePath(
  process.env.OPENRAG_FRONTEND_BASE_PATH,
);

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

const nextConfig: NextConfig = {
  // `basePath` is compiled into the browser bundle. The same value is exposed
  // below so the Axios API client calls /<basePath>/api rather than /api.
  basePath: frontendBasePath,
  env: {
    NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH: frontendBasePath,
  },
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

export default nextConfig;
