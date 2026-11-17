import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The dev server is opened through 127.0.0.1 by the desktop preview.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
