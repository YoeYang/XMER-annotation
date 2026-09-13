import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// e2e 与本地开发都需要把 /api 转给后端；线上由 Caddy 承担同样的转发。
const apiTarget = process.env.VITE_API_TARGET;

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? "/",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: apiTarget
      ? {
          "/api": {
            target: apiTarget,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => "/annotation" + path,
          },
        }
      : undefined,
  },
  test: { include: ["tests/**/*.test.ts"] },
});
