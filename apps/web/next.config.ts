import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";

// Everything the app loads comes from its own origin (fonts are self-hosted by next/font).
// Next.js inlines small scripts, so script-src needs 'unsafe-inline'; development also needs
// eval and a websocket for hot reload.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "frame-src 'self' blob:",
  "frame-ancestors 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const common = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  devIndicators: false,
  poweredByHeader: false,
  // The Mac app builds into its own folder so `next dev` never overwrites the production build.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async headers() {
    return [
      {
        // Pages. Resume previews are framed from /api, so framing is limited to this origin.
        source: "/((?!api/).*)",
        headers: [
          ...common,
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
        ],
      },
      {
        // Proxied API responses: personal data, never cached, never sent as a referrer.
        source: "/api/:path*",
        headers: [...common, { key: "Referrer-Policy", value: "no-referrer" }, { key: "Cache-Control", value: "no-store" }],
      },
    ];
  },
};

export default nextConfig;
