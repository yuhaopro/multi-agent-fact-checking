import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.BACKEND_URL || "http://localhost:8081"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
