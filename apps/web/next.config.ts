import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const apiServerUrl = (
      process.env.CLIPPER_API_SERVER_URL ?? "http://localhost:8001"
    ).replace(/\/$/, "");

    return [
      {
        source: "/backend-api/:path*",
        destination: `${apiServerUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
