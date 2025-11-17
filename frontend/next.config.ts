import type { NextConfig } from "next";
import dotenv from "dotenv";
import path from "path";

// Load environment variables from root .env file
dotenv.config({ path: path.resolve(__dirname, "../.env") });

const nextConfig: NextConfig = {
  // Increase timeout for API routes
  experimental: {
    proxyTimeout: 300000, // 5 minutes
  },
  // Ignore ESLint errors during build
  eslint: {
    ignoreDuringBuilds: true,
  },
  env: {
    UPDATED_ONBOARDING: process.env.UPDATED_ONBOARDING,
  },
};

export default nextConfig;
