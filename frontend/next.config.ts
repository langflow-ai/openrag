import dotenv from "dotenv";
import type { NextConfig } from "next";
import path from "path";

// Load environment variables from the root env file. Honors ENV_FILE (set by
// the Makefile) so per-instance env files like `.env.instance2` are respected;
// defaults to `.env`. Absolute ENV_FILE paths are used as-is.
dotenv.config({
  path: path.resolve(process.cwd(), "..", process.env.ENV_FILE || ".env"),
});

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

function browserSourceMapsEnabled(): boolean {
  // Minified client bundles make a production crash report nearly unusable: a
  // stack arrives as `a.className` in `1qo6lnr83k_k3.js:31:3093`, with no way
  // to reach the component or the line. Enabling this emits .map files beside
  // the chunks so the browser resolves those frames itself.
  //
  // Off by default. Source maps let anyone who can fetch the assets read the
  // original source, so this is opt-in per deployment rather than always on —
  // dev and staging images, where diagnosing a QA report is worth more than
  // the obscurity, and where the assets already sit behind authentication.
  const raw = process.env.OPENRAG_BROWSER_SOURCE_MAPS;
  return ["true", "1", "yes", "on"].includes((raw ?? "").trim().toLowerCase());
}

const nextConfig: NextConfig = {
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
  // Ship client source maps when OPENRAG_BROWSER_SOURCE_MAPS is set, so a
  // minified stack from a deployed build can be read. See the note above.
  productionBrowserSourceMaps: browserSourceMapsEnabled(),
};

export default nextConfig;
