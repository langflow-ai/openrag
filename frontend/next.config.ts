import type { NextConfig } from "next";
import dotenv from "dotenv";
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
  // Ignore ESLint errors during build
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Allow cross-origin requests in development
  allowedDevOrigins: getAllowedDevOrigins(),
};

export default nextConfig;
