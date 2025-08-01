import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Increase timeout for API routes
  experimental: {
    proxyTimeout: 300000, // 5 minutes
  },
};

export default nextConfig;
