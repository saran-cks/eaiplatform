import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The Core API has no CORS middleware (it only verifies a bearer JWT), so in dev
// we proxy the API surface through Vite to keep everything same-origin. The
// frontend `api/client.ts` targets relative paths by default; set
// VITE_API_BASE_URL to point at an absolute origin (e.g. behind a CDN in prod).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_DEV_API_PROXY_TARGET || "http://localhost:8000";

  // Every top-level Core API route prefix (verified against src/api/routes/).
  const proxied = [
    "/chat",
    "/agent",
    "/search",
    "/observability",
    "/feedback",
    "/health",
    "/ready",
    "/openapi.json",
  ];

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: 5173,
      proxy: Object.fromEntries(
        proxied.map((path) => [
          path,
          {
            target: apiTarget,
            changeOrigin: true,
            // SSE endpoints stream; never buffer the proxied response.
            configure: (proxy) => {
              proxy.on("proxyRes", (proxyRes) => {
                if (
                  proxyRes.headers["content-type"]?.includes("text/event-stream")
                ) {
                  proxyRes.headers["cache-control"] = "no-cache";
                }
              });
            },
          },
        ]),
      ),
    },
  };
});
