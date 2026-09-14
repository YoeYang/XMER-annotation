/**
 * 抓线上标注页的实拍图。默认标完一轮，拍下罗盘下方的曲线图。
 * 用法见 server/README.md 的端到端一节（需要 E2E_BASE_URL 与 E2E_TOKEN）。
 */
import { chromium } from "@playwright/test";

const base = process.env.E2E_BASE_URL, tok = process.env.E2E_TOKEN;
const browser = await chromium.launch();
const page = await (
  await browser.newContext({
    viewport: { width: 1560, height: 1100 },
    ignoreHTTPSErrors: true,
  })
).newPage();

await page.goto(`${base}/annotation/?t=${tok}`);
await page.locator(".sample-list").waitFor();

const group = page.locator(".sample-group").first();
if (!(await group.locator(".modality-item").first().isVisible()))
  await group.locator(".sample-header").click();
await group.getByRole("button", { name: /仅视觉/ }).click();
await page.locator(".media-panel").waitFor();

const pad = page.getByRole("button", { name: "二维情绪标注区域" });
await pad.click({ position: { x: 130, y: 80 } });
// 边播边画出一条有起伏的曲线
for (let i = 0; i < 40; i++) {
  await pad.hover({ position: { x: 40 + i * 6, y: 60 + Math.sin(i / 4) * 45 } });
  await page.waitForTimeout(120);
}
await page.locator(".curve-panel").waitFor({ timeout: 30000 });
await page.waitForTimeout(500);
await page.screenshot({ path: "/src/shot-curve.png" });
await page.locator(".annotation-panel").screenshot({ path: "/src/shot-curve-zoom.png" });

await browser.close();
