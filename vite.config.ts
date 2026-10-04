import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// e2e 与本地开发都需要把 /api 转给后端；线上由 Caddy 承担同样的转发。
const apiTarget = process.env.VITE_API_TARGET;

// 每次构建一个版本号：写进代码，也写成 dist/version.json，页面据此发现新版本（src/core/version.ts）
const buildId = process.env.BUILD_ID ?? new Date().toISOString();

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? "/",
  define: { __APP_VERSION__: JSON.stringify(buildId) },
  plugins: [
    react(),
    {
      name: "xmer-version-file",
      generateBundle() {
        this.emitFile({
          type: "asset",
          fileName: "version.json",
          source: JSON.stringify({ version: buildId }),
        });
      },
    },
  ],
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
