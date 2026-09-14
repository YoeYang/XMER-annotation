import { chromium } from "@playwright/test";
const base = process.env.E2E_BASE_URL, tok = process.env.E2E_TOKEN;
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 1560, height: 1000 }, ignoreHTTPSErrors: true })).newPage();
await p.goto(`${base}/annotation/?t=${tok}`);
await p.locator(".sample-list").waitFor();
for (const [name, modality] of [["visual", "仅视觉"], ["text", "仅文本"]]) {
  const g = p.locator(".sample-group").first();
  if (!(await g.locator(".modality-item").first().isVisible())) await g.locator(".sample-header").click();
  await g.getByRole("button", { name: new RegExp(modality) }).click();
  await p.locator(".media-panel").waitFor();
  await p.getByRole("button", { name: "二维情绪标注区域" }).click({ position: { x: 130, y: 80 } });
  await p.waitForTimeout(2200);
  await p.screenshot({ path: `/src/shot-${name}.png` });
}
await b.close();
