import { test, expect, type Page } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import type { ExportData } from "../src/types";

async function open(page: Page) {
  page.on("dialog", (dialog) => void dialog.accept());
  await page.goto("/");
  await expect(page.getByText("等待开始", { exact: true })).toBeVisible();
}
async function annotate(page: Page) {
  await page.getByLabel("播放速度").selectOption("1.5");
  await page.getByRole("button", { name: "二维情绪标注区域" }).click();
  await expect(page.getByText("正在采样", { exact: true })).toBeVisible();
}
async function finished(page: Page) {
  await expect(page.getByText("本轮已完成", { exact: true })).toBeVisible({
    timeout: 20000,
  });
}
async function download(page: Page): Promise<ExportData> {
  const waiting = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 JSON" }).click();
  const file = await waiting;
  return JSON.parse(await readFile((await file.path())!, "utf8"));
}

test("桌面与窄屏布局、目录搜索和指南", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await open(page);
  await mkdir("artifacts", { recursive: true });
  await page.screenshot({ path: "artifacts/desktop.png", fullPage: true });
  await page.getByLabel("搜索样本").fill("字里");
  await expect(
    page.getByRole("navigation", { name: "样本目录" }).getByRole("button"),
  ).toHaveCount(1);
  await page.getByLabel("搜索样本").fill("");
  await page.getByRole("button", { name: "标注指南", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "我知道了，开始标注" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "artifacts/mobile.png", fullPage: true });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  const pad = await page
    .getByRole("button", { name: "二维情绪标注区域" })
    .boundingBox();
  expect(Math.abs(pad!.width - pad!.height)).toBeLessThan(2);
  expect(errors).toEqual([]);
});

test("四种材料真实播放并自然结束，预览不产生正式样本", async ({ page }) => {
  await open(page);
  for (const name of ["光影之间", "听见变化", "字里行间", "声音与画面"]) {
    await page
      .getByRole("navigation", { name: "样本目录" })
      .getByRole("button", { name: new RegExp(name) })
      .click();
    await expect(page.getByText("等待开始", { exact: true })).toBeVisible();
    await page.getByLabel("播放速度").selectOption("1.5");
    await page.getByRole("button", { name: "预览材料", exact: true }).click();
    await expect(page.getByText("正在预览", { exact: true })).toBeVisible();
    await finished(page);
    await expect(page.getByTestId("sample-count")).toHaveText("0 点");
  }
  const data = await download(page);
  expect(data.attempts).toHaveLength(4);
  expect(
    data.attempts.every(
      (a) =>
        a.mode === "preview" && a.status === "completed" && !a.samples.length,
    ),
  ).toBe(true);
});

test("预览结束后可直接点击二维区域开始正式标注", async ({ page }) => {
  await open(page);
  await page.getByLabel("播放速度").selectOption("1.5");
  await page.getByRole("button", { name: "预览材料", exact: true }).click();
  await finished(page);
  await expect(
    page.getByRole("button", { name: "二维情绪标注区域" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "二维情绪标注区域" }).click();
  await expect(page.getByText("正在采样", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "暂停播放" }).click();
  const data = await download(page);
  expect(data.attempts.map((a) => a.mode)).toEqual(["preview", "annotation"]);
  expect(data.attempts[0].status).toBe("completed");
  expect(data.attempts[1].sample_count).toBeGreaterThan(0);
});

test("采样、暂停、离开方形、Submit、Update 与刷新后读取历史", async ({
  page,
}) => {
  await open(page);
  await annotate(page);
  await expect
    .poll(async () =>
      parseInt(await page.getByTestId("sample-count").innerText(), 10),
    )
    .toBeGreaterThan(3);
  const box = await page
    .getByRole("button", { name: "二维情绪标注区域" })
    .boundingBox();
  await page.mouse.move(box!.x + box!.width * 0.8, box!.y + box!.height * 0.2);
  await expect(page.getByTestId("valence")).toHaveText("0.60");
  await page.mouse.move(10, 10);
  const before = parseInt(
    await page.getByTestId("sample-count").innerText(),
    10,
  );
  await expect
    .poll(async () =>
      parseInt(await page.getByTestId("sample-count").innerText(), 10),
    )
    .toBeGreaterThan(before + 2);
  await page.getByRole("button", { name: "暂停播放" }).click();
  await expect(page.getByText("已暂停", { exact: true })).toBeVisible();
  const pausedValence = await page.getByTestId("valence").innerText();
  await page.mouse.move(box!.x + box!.width * 0.2, box!.y + box!.height * 0.8);
  await expect(page.getByTestId("valence")).toHaveText(pausedValence);
  const paused = await page.getByTestId("sample-count").innerText();
  await page.waitForTimeout(400);
  await expect(page.getByTestId("sample-count")).toHaveText(paused);
  await page.getByRole("button", { name: "继续播放" }).click();
  await finished(page);
  await page.getByRole("button", { name: "Submit 提交" }).click();
  await expect(
    page.getByText("Submit 成功，结果已保存到本地。", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "样本目录" })
      .getByRole("button", { name: /光影之间/ }),
  ).toContainText("已提交");
  const first = await download(page);
  expect(first.submissions).toHaveLength(1);
  expect(first.attempts[0].samples[0].media_time).toBe(0);
  expect(first.attempts[0].samples.at(-1)!.media_time).toBeCloseTo(12, 1);
  await page.getByRole("button", { name: "重新标注", exact: true }).click();
  await expect(page.getByTestId("sample-count")).toHaveText("0 点");
  await annotate(page);
  await finished(page);
  await expect(
    page
      .getByRole("navigation", { name: "样本目录" })
      .getByRole("button", { name: /光影之间/ }),
  ).toContainText("待更新");
  await page.getByRole("button", { name: "Update 更新" }).click();
  await expect(
    page.getByText("Update 成功，历史原始记录已保留。", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("等待开始", { exact: true })).toBeVisible();
  const data = await download(page);
  expect(data.submissions.map((s) => s.revision)).toEqual([1, 2]);
  expect(data.attempts).toHaveLength(2);
  expect(data.attempts[0].samples).toEqual(first.attempts[0].samples);
  expect(new Set(data.attempts.map((a) => a.attempt_id)).size).toBe(2);
  for (const a of data.attempts) {
    expect(a.completed_at).not.toBeNull();
    expect(
      a.samples.every(
        (s, i) =>
          s.sample_index === i &&
          (i === 0 || s.media_time > a.samples[i - 1].media_time),
      ),
    ).toBe(true);
  }
});

test("完成后未提交的草稿可刷新恢复并提交", async ({ page }) => {
  await open(page);
  await annotate(page);
  await finished(page);
  await expect(
    page.getByRole("status").filter({ hasText: "已保存到本地" }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("等待开始", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit 提交" })).toBeEnabled();
  await page.getByRole("button", { name: "Submit 提交" }).click();
  expect((await download(page)).submissions).toHaveLength(1);
});

test("刷新恢复未完成轮次，记录中断且不能提交", async ({ page }) => {
  await open(page);
  await annotate(page);
  await expect
    .poll(async () =>
      parseInt(await page.getByTestId("sample-count").innerText(), 10),
    )
    .toBeGreaterThan(12);
  await page.reload();
  await expect(page.getByText("等待开始", { exact: true })).toBeVisible();
  const data = await download(page);
  expect(data.attempts[0].status).toBe("interrupted");
  expect(data.attempts[0].completed_at).toBeNull();
  expect(data.attempts[0].samples.length).toBeGreaterThan(0);
  await expect(
    page.getByRole("button", { name: "Submit 提交" }),
  ).toBeDisabled();
});

test("文本逐步出现且暂停保持当前文字", async ({ page }) => {
  await open(page);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /字里行间/ })
    .click();
  await expect(page.getByText("等待开始", { exact: true })).toBeVisible();
  await page.getByLabel("播放速度").selectOption("0.5");
  await page.getByRole("button", { name: "预览材料", exact: true }).click();
  await expect(page.getByTestId("transcript")).toHaveText("有时候，");
  await page.getByRole("button", { name: "暂停播放" }).click();
  const text = await page.getByTestId("transcript").innerText();
  await page.waitForTimeout(400);
  await expect(page.getByTestId("transcript")).toHaveText(text);
});

test("无效媒体与文本时间戳阻止开始并给出反馈", async ({ page }) => {
  await page.route("**/media/visual.mp4", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText("加载或播放失败", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "预览材料", exact: true }),
  ).toBeDisabled();
  await page.route("**/transcripts/demo.json", (route) =>
    route.fulfill({ json: { duration: 0, sentences: [] } }),
  );
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /字里行间/ })
    .click();
  await expect(
    page.getByText("文本时长与任务不一致", { exact: true }),
  ).toBeVisible();
});

test("第二个页面不能同时编辑同一个本地数据库", async ({ page, context }) => {
  await open(page);
  const second = await context.newPage();
  await second.goto("/");
  await expect(second.getByRole("alert")).toContainText(
    "另一个页面正在使用本地工作区",
  );
  await second.close();
});
