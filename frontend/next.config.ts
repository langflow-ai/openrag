import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/:path*',
      },
    ];
  },
  // Increase timeout for API routes
  experimental: {
    proxyTimeout: 300000, // 5 minutes
  },
};

export default nextConfig;
