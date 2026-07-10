import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  // Emit a self-contained server bundle so the Docker image stays small.
  // Harmless for the native deploy — `next start` still works as before.
  output: "standalone",
  // Security headers — cheap defense-in-depth for the one page that renders
  // LLM output. connect-src must include the backend origin the browser calls
  // (NEXT_PUBLIC_API_URL, baked in at build time); dev stays relaxed so HMR
  // and localhost API calls keep working.
  async headers() {
    const dev = process.env.NODE_ENV !== "production";
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const apiOrigin = api.startsWith("http") ? ` ${new URL(api).origin}` : "";
    const csp = [
      "default-src 'self'",
      "img-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      "script-src 'self' 'unsafe-inline'" + (dev ? " 'unsafe-eval'" : ""),
      `connect-src 'self'${apiOrigin}` + (dev ? " http://localhost:8000 ws:" : ""),
      "frame-ancestors 'none'",
    ].join("; ");
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Content-Security-Policy", value: csp },
        ],
      },
    ];
  },
};

export default nextConfig;
