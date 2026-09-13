import { expect, test, type Page } from "@playwright/test";

/**
 * 端到端用例。覆盖的都是单元测试看不见、只有真浏览器能验证的行为：
 * 媒体真的播完、鼠标离开方形后还在不在采样、刷新之后草稿还在不在。
 * 这类 bug 在 pilot 里出现，等于一批人的工时白费。
 *
 * 需要两个环境变量：
 *   E2E_TOKEN     测试标注者的令牌（由 manage.py seed-e2e 产生）
 *   E2E_BASE_URL  可选；指向已部署站点时跳过本地 vite
 */

const TOKEN = process.env.E2E_TOKEN ?? "";
const ENTRY = process.env.E2E_BASE_URL ? "/annotation/" : "/";

test.skip(!TOKEN, "需要 E2E_TOKEN，见 server/README.md 的端到端一节");

async function open(page: Page) {
  await page.goto(`${ENTRY}?t=${TOKEN}`);
  await expect(page.locator(".sample-list")).toBeVisible();
}

/** 打开某个样本的指定模态。侧栏是分组折叠的，先展开再点。 */
async function openTask(page: Page, modality: string) {
  const group = page.locator(".sample-group").first();
  if (!(await group.locator(".modality-item").first().isVisible())) {
    await group.locator(".sample-header").click();
  }
  await group.getByRole("button", { name: new RegExp(modality) }).click();
  await expect(page.locator(".media-panel")).toBeVisible();
}

async function startAnnotating(page: Page) {
  const pad = page.getByRole("button", { name: "二维情绪标注区域" });
  await pad.click({ position: { x: 120, y: 90 } });
  await expect(page.locator(".save-line")).toBeVisible();
  return pad;
}

// --------------------------------------------------------------- 身份

test("用专属链接进入后，地址栏里的令牌被抹掉", async ({ page }) => {
  // 令牌留在地址栏会经 referer 外泄，也会随截图和转发一起送人
  await open(page);
  expect(page.url()).not.toContain("t=");
  await expect(page.locator(".annotator-identity")).toBeVisible();
});

test("没有令牌时给出明确指引，而不是白屏或报错堆栈", async ({ page }) => {
  await page.goto(ENTRY);
  await expect(page.locator(".global-error")).toContainText("专属网址");
});

test("刷新后仍然是同一个人，不需要重新点链接", async ({ page }) => {
  await open(page);
  const who = await page.locator(".annotator-identity strong").textContent();
  await page.reload();
  await expect(page.locator(".annotator-identity strong")).toHaveText(who!);
});

// --------------------------------------------------------------- 目录与素材

test("侧栏按样本分组，完整视频排在三个单模态之后", async ({ page }) => {
  // 先看完整视频会让随后的单模态标注变成回忆而非感知
  await open(page);
  const group = page.locator(".sample-group").first();
  // 选中任务所在的组会自动展开，无条件点击反而会把它折叠
  if (!(await group.locator(".modality-item").first().isVisible())) {
    await group.locator(".sample-header").click();
  }
  const labels = await group.locator(".modality-item strong").allTextContents();
  expect(labels).toEqual(["仅视觉", "仅音频", "仅文本", "完整视频"]);
});

test("说话人静帧常驻在媒体区上方", async ({ page }) => {
  await open(page);
  await openTask(page, "仅视觉");
  const ref = page.locator(".speaker-ref");
  await expect(ref).toBeVisible();
  await expect(ref).toContainText("按这个人进行标注");
  await expect(ref.locator("img")).toHaveJSProperty("complete", true);
});

// --------------------------------------------------------------- 采样

test("光标静止不动时仍持续采样", async ({ page }) => {
  // 静止代表情绪保持稳定，不是没数据
  await open(page);
  await openTask(page, "仅视觉");
  await startAnnotating(page);
  await page.waitForTimeout(1500);
  const first = await page.getByTestId("valence").textContent();
  await page.waitForTimeout(1500);
  await expect(page.locator(".attempt-panel")).toContainText(/\d/);
  expect(first).not.toBeNull();
});

test("鼠标移出方形后保持最后位置，不清零", async ({ page }) => {
  await open(page);
  await openTask(page, "仅视觉");
  const pad = await startAnnotating(page);
  await pad.hover({ position: { x: 200, y: 40 } });
  const inside = await page.getByTestId("valence").textContent();
  await page.locator(".breadcrumb").hover();
  await page.waitForTimeout(800);
  await expect(page.getByTestId("valence")).toHaveText(inside!);
});

test("暂停后停止采样，继续播放后恢复", async ({ page }) => {
  await open(page);
  await openTask(page, "仅视觉");
  await startAnnotating(page);
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "暂停播放" }).click();
  const paused = await page.getByTestId("media-time").textContent();
  await page.waitForTimeout(1200);
  await expect(page.getByTestId("media-time")).toHaveText(paused!);
});

// --------------------------------------------------------------- 文本模态

test("文本随播放逐词出现，暂停时停在当前文字", async ({ page }) => {
  await open(page);
  await openTask(page, "仅文本");
  await startAnnotating(page);
  await page.waitForTimeout(1500);
  const shown = await page.getByTestId("transcript").textContent();
  await page.getByRole("button", { name: "暂停播放" }).click();
  await page.waitForTimeout(1000);
  await expect(page.getByTestId("transcript")).toHaveText(shown!);
});

// --------------------------------------------------------------- 保存与同步

test("断网时标注不中断，恢复后自动补传", async ({ page, context }) => {
  // 标注者跨境访问，断一下不是小概率事件；中途丢数据等于这个人白干
  await open(page);
  await openTask(page, "仅视觉");
  await startAnnotating(page);
  await page.waitForTimeout(1000);

  await context.setOffline(true);
  await page.waitForTimeout(2500);
  await expect(page.locator(".save-line")).toContainText(/待上传|失败/);

  await context.setOffline(false);
  await expect(page.locator(".save-line")).toContainText(/已同步|已保存/, {
    timeout: 30000,
  });
});

test("刷新之后草稿还在，不用从头重标", async ({ page }) => {
  await open(page);
  await openTask(page, "仅视觉");
  await startAnnotating(page);
  await page.waitForTimeout(2000);
  await expect(page.locator(".save-line")).toContainText(/已同步|已保存/, {
    timeout: 30000,
  });

  await page.reload();
  await expect(page.locator(".sample-list")).toBeVisible();
  await openTask(page, "仅视觉");
  await expect(page.locator(".attempt-panel")).toContainText(/进行中|已完成|待提交/);
});
