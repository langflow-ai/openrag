/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import dotenv from "dotenv";
import type { NextConfig } from "next";
import path from "path";

// Load environment variables from root .env file
dotenv.config({ path: path.resolve(__dirname, "../.env") });

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
