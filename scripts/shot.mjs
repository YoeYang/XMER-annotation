/**
 * 抓线上标注页的实拍图，四个模态各一张，外加一张展开"标注详情"的。
 * 用法见 server/README.md 的端到端一节（同样需要 E2E_BASE_URL 与 E2E_TOKEN）。
 */
import { chromium } from "@playwright/test";

const base = process.env.E2E_BASE_URL, tok = process.env.E2E_TOKEN;
const browser = await chromium.launch();
const page = await (
  await browser.newContext({
    viewport: { width: 1560, height: 1040 },
    ignoreHTTPSErrors: true,
  })
).newPage();

await page.goto(`${base}/annotation/?t=${tok}`);
await page.locator(".sample-list").waitFor();

const open = async (modality) => {
  const group = page.locator(".sample-group").first();
  if (!(await group.locator(".modality-item").first().isVisible()))
    await group.locator(".sample-header").click();
  await group.getByRole("button", { name: new RegExp(modality) }).click();
  await page.locator(".media-panel").waitFor();
};

for (const [name, modality] of [
  ["1-visual", "仅视觉"],
  ["2-audio", "仅音频"],
  ["3-text", "仅文本"],
  ["4-audiovisual", "完整视频"],
]) {
  await open(modality);
  await page
    .getByRole("button", { name: "二维情绪标注区域" })
    .click({ position: { x: 130, y: 80 } });
  await page.waitForTimeout(2200);
  await page.screenshot({ path: `/src/shot-${name}.png` });
}

// 折叠块展开后的样子：轮次、完成时间、提交版本都在里面
await page.locator(".attempt-panel > summary").click();
await page.waitForTimeout(300);
await page.locator(".attempt-panel").scrollIntoViewIfNeeded();
await page.screenshot({ path: "/src/shot-5-details.png" });

await browser.close();
