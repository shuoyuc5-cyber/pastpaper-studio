import type { NextConfig } from "next";

const apiPort = Number(process.env.PASTPAPER_BACKEND_PORT ?? 8000);
if (!Number.isInteger(apiPort) || apiPort < 1 || apiPort > 65535) throw new Error('Invalid loopback API port');

const nextConfig: NextConfig = {
  poweredByHeader: false,
  images: { unoptimized: true },
  async headers() {
    return [{ source: '/:path*', headers: [
      {key:'X-Content-Type-Options',value:'nosniff'},
      {key:'X-Frame-Options',value:'DENY'},
      {key:'Referrer-Policy',value:'no-referrer'},
      {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'},
      {key:'Content-Security-Policy',value:"frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"},
    ]}];
  },
  distDir: process.env.PASTPAPER_DIST_DIR || ".next",
  experimental: { proxyTimeout: 150_000 },
  async rewrites() {
    if (process.env.PASTPAPER_PUBLIC_ORIGIN) return [];
    return [{ source: "/api/:path*", destination: `http://127.0.0.1:${apiPort}/api/:path*` }];
  },
};

export default nextConfig;
