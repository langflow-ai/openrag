import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Increase timeout for API routes
  experimental: {
    proxyTimeout: 300000, // 5 minutes
  },
  // Ignore ESLint errors during build
  eslint: {
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    const backendHost = process.env.OPENRAG_BACKEND_HOST || 'localhost';
    const backendPort = process.env.OPENRAG_BACKEND_PORT || '8000';
    const backendSSL = process.env.OPENRAG_BACKEND_SSL === 'true';
    const protocol = backendSSL ? 'https' : 'http';
    const backendBaseUrl = `${protocol}://${backendHost}:${backendPort}`;

    return [
      {
        source: '/widgets/:path*',
        destination: `${backendBaseUrl}/widgets/:path*`,
      },
    ];
  },
};

export default nextConfig;