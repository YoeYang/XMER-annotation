/**
 * 抓线上标注页的实拍图：把四个模态都标完并提交，拍下罗盘下方的四条曲线。
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

const pad = page.getByRole("button", { name: "二维情绪标注区域" });
const shapes = [
  (i) => 60 + Math.sin(i / 5) * 55,
  (i) => 150 - i * 2.2,
  (i) => 70 + ((i * 7) % 60),
  (i) => 110 + Math.cos(i / 6) * 40,
];

for (const [n, modality] of ["仅视觉", "仅音频", "仅文本", "完整视频"].entries()) {
  const group = page.locator(".sample-group").first();
  if (!(await group.locator(".modality-item").first().isVisible()))
    await group.locator(".sample-header").click();
  await group.getByRole("button", { name: new RegExp(modality) }).click();
  await page.locator(".media-panel").waitFor();

  await pad.click({ position: { x: 120, y: shapes[n](0) } });
  for (let i = 1; i < 36; i++) {
    await pad.hover({ position: { x: 30 + i * 7, y: shapes[n](i) } });
    await page.waitForTimeout(110);
  }
  // 侧栏的「已提交」筛选标签同名，按主按钮定位
  const send = page.locator(".action-buttons .button.primary");
  await send.waitFor();
  await page.waitForFunction(
    () => !document.querySelector(".action-buttons .button.primary")?.disabled,
    null,
    { timeout: 30000 },
  );
  await send.click();
  await page.locator(".operation-notice").waitFor({ timeout: 30000 });
}

await page.locator(".curve-panel").waitFor({ timeout: 30000 });
await page.waitForTimeout(600);
await page.screenshot({ path: "/src/shot-curve.png" });
await page.locator(".annotation-panel").screenshot({ path: "/src/shot-curve-zoom.png" });

await browser.close();
