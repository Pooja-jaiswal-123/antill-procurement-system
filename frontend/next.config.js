// All browser calls go to /api/* on this Next.js app, which proxies to the FastAPI backend (no CORS issues).
const API = process.env.API_URL || "http://localhost:8000";
module.exports = {
  experimental: { proxyTimeout: 120000 },
  async rewrites() { return [{ source: "/api/:path*", destination: `${API}/api/:path*` }]; },
};
