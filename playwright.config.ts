import { defineConfig } from "@playwright/test";

// 不写死任何本机路径或浏览器渠道：Windows 开发机、ECS 上的容器都要能跑。
// E2E_BASE_URL 指向已起好的站点时跳过 webServer，否则本地拉起 vite。
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const external = Boolean(process.env.E2E_BASE_URL);

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 90000,
  expect: { timeout: 15000 },
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1440, height: 1100 },
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
  },
  reporter: [["list"]],
  webServer: external
    ? undefined
    : {
        command: "npx vite --host 127.0.0.1",
        url: baseURL,
        reuseExistingServer: true,
        timeout: 120000,
      },
});
