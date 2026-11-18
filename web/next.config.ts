import path from "node:path";

import type { NextConfig } from "next";

// The engine runs on loopback. Proxying /v1 through this server means the
// browser only ever talks to its own origin, which is what makes the demo work
// from a tunnel: Chrome blocks a public HTTPS page (ngrok) from calling
// http://127.0.0.1 directly under Private Network Access, and a direct call
// would also need CORS to agree with a tunnel hostname that changes per restart.
const API_ORIGIN = (
  process.env.PHYTOLENS_API_ORIGIN ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The repo root has its own package-lock.json (the Playwright/QA tooling), so
  // Next guessed the wrong tracing root and warned on every boot.
  outputFileTracingRoot: path.join(__dirname),
  // The floating dev badge sits over the footer in screenshots and demos.
  devIndicators: false,
  experimental: {
    // A cold live-dock runs real Vina: two compounds on one target takes about
    // 30 s here, and two targets about a minute. The proxy default of 30 s
    // killed the connection mid-run, so the browser saw a 500 from its own
    // origin while the engine kept working. Give the dock room to answer.
    proxyTimeout: 180_000,
  },
  // The dev server is opened through loopback by the desktop preview, and
  // through a tunnel when the demo is shared. Without these the tunnel serves
  // the HTML but blocks every /_next/* asset, so the page renders blank.
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "*.ngrok-free.dev",
    "*.ngrok-free.app",
    "*.ngrok.io",
    "*.trycloudflare.com",
  ],
  async rewrites() {
    return [{ source: "/v1/:path*", destination: `${API_ORIGIN}/v1/:path*` }];
  },
};

export default nextConfig;
