import { expect, test, type Page, type Route } from "@playwright/test";
import type { Attempt, Sample, Submission, Task } from "../src/types";

// Each browser test gets an isolated V3 API. No research account or live data is used.
test.use({ channel: process.env.E2E_BROWSER_CHANNEL || undefined });

test.beforeEach(async ({ page }) => {
  const modalities: Task["modality"][] = [
    "face",
    "body",
    "audio",
    "text",
    "audiovisual",
  ];
  const tasks: Task[] = modalities.flatMap((modality) =>
    [0, 1].map((order_index) => ({
      task_id: modality + "-" + order_index,
      media_id: "private-source-" + order_index,
      display_id: "S0001",
      modality,
      src:
        modality === "text"
          ? "/transcripts/example.json"
          : modality === "audio"
            ? "/media/example/audio.wav"
            : "/media/example/visual.mp4",
      duration: 6.715,
      target: "目标说话人",
      demo: true,
      timeline_origin: 0,
      order_index,
      speaker_ref_src: "/media/example/speaker.jpg",
    })),
  );
  const attempts = new Map<string, Attempt>();
  const samples = new Map<string, Map<number, Sample>>();
  const submissions = new Map<string, Submission>();
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.split("/api")[1];
    const parts = path.split("/").filter(Boolean);
    let result: unknown = {};
    if (path === "/me") {
      result = {
        annotator_id: "P3-07",
        display_name: "测试标注员",
        phase: "main",
        tasks,
      };
    } else if (path === "/attempts") {
      result = [...attempts.values()];
    } else if (path === "/submissions") {
      result = [...submissions.values()];
    } else if (parts[0] === "attempts" && request.method() === "PUT") {
      const id = parts[1];
      const body = request.postDataJSON();
      if (parts[2] === "chunks") {
        const saved = samples.get(id) ?? new Map<number, Sample>();
        for (const sample of body.samples)
          saved.set(sample.sample_index, sample);
        samples.set(id, saved);
      } else {
        attempts.set(id, {
          ...body,
          schema_version: 1,
          attempt_id: id,
          annotator_id: "P3-07",
          sample_count: 0,
          last_media_time: 0,
          calibration: null,
        });
      }
      const attempt = attempts.get(id);
      if (attempt) {
        const rows = [...(samples.get(id)?.values() ?? [])];
        attempt.sample_count = rows.length;
        attempt.last_media_time = rows.at(-1)?.media_time ?? 0;
      }
      result = attempt ?? {};
    } else if (parts[2] === "submit") {
      const attempt = attempts.get(parts[1])!;
      const body = request.postDataJSON();
      const submission: Submission = {
        submission_id: body.submission_id,
        attempt_id: attempt.attempt_id,
        task_id: attempt.task_id,
        annotator_id: "P3-07",
        revision: 1,
        previous_submission_id: null,
        submitted_at: new Date().toISOString(),
        updated_at: null,
      };
      submissions.set(submission.submission_id, submission);
      result = submission;
    } else if (parts[2] === "samples") {
      result = [...(samples.get(parts[1])?.values() ?? [])];
    }
    await route.fulfill({ json: result });
  });
});

async function open(page: Page) {
  await page.goto("/?t=frontend-test");
  await expect(page.locator(".sample-list")).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText("面部 · 标注指南");
  await page.getByRole("button", { name: "知道了" }).click();
  await expect
    .poll(() =>
      page
        .locator(".media-stage video")
        .evaluate((media: HTMLVideoElement) => media.readyState),
    )
    .toBeGreaterThanOrEqual(2);
}

async function enterValence(page: Page) {
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("效价 Valence标注条")).toBeVisible();
  await expect(page.getByLabel("播放速度")).toHaveValue("0.5");
  await expect.poll(() => mediaTime(page)).toBe(0);
}

/** 在竖直标注条上按住。`ratio` 是**从上往下**的比例：0 为 +1、1 为 −1。 */
async function pressBar(page: Page, ratio = 0.5) {
  const box = await page
    .locator(".dimension-row.active .dimension-bar")
    .boundingBox();
  if (!box) throw new Error("标注条不可见");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * ratio);
  await page.mouse.down();
  return box;
}

async function mediaTime(page: Page) {
  return page
    .locator(".media-stage video, .media-stage audio")
    .evaluate((media: HTMLMediaElement) => media.currentTime);
}

async function records(
  page: Page,
  store: "attempts" | "samples" | "submissions",
) {
  return page.evaluate(
    (storeName) =>
      new Promise<any[]>((resolve, reject) => {
        const request = indexedDB.open("xmer-annotation-v1", 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          const db = request.result;
          const read = db
            .transaction(storeName)
            .objectStore(storeName)
            .getAll();
          read.onsuccess = () => {
            resolve(read.result);
            db.close();
          };
          read.onerror = () => {
            reject(read.error);
            db.close();
          };
        };
      }),
    store,
  );
}

test("令牌清除，身份刷新后保留", async ({ page }) => {
  await open(page);
  expect(page.url()).not.toContain("t=");
  await page.reload();
  await expect(page.locator(".annotator-identity")).toContainText("测试标注员");
});

test("没有令牌显示入口提示", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".global-error")).toContainText("专属网址");
});

test("五模态顺序与侧栏折叠宽度", async ({ page }) => {
  await open(page);
  await expect(page.locator(".task-section-heading strong")).toHaveText([
    "S1 面部",
    "S2 身体",
    "S3 音频",
    "S4 文本",
    "S5 完整",
  ]);
  await page.getByRole("button", { name: "收起侧栏 Collapse" }).click();
  await expect(page.locator(".v3-sidebar")).toHaveCSS("width", "56px");
  await page.getByRole("button", { name: "展开侧栏 Expand" }).click();
  await expect(page.locator(".sample-list")).toBeVisible();
});

test("仅显示块内序号与工单号", async ({ page }) => {
  await open(page);
  await expect(page.locator(".workspace-heading")).toContainText("面部 1/2");
  await expect(page.locator(".sidebar-ticket strong")).toHaveText(
    "P3-07-face-01",
  );
  await expect(page.locator("body")).not.toContainText(/S0001|private-source/);
});

test("熟悉页自动播放 1 倍速，保留说话人，无说明卡片", async ({ page }) => {
  await open(page);
  await expect(page.getByLabel("播放速度")).toHaveValue("1");
  await expect(page.getByAltText("目标说话人 Target speaker")).toBeVisible();
  await expect(page.locator(".speaker-ref")).toContainText(
    "请标注这位说话人的情绪",
  );
  await expect.poll(() => mediaTime(page)).toBeGreaterThan(0);
  await expect(
    page.locator(".three-step-progress, .eyebrow, .save-line"),
  ).toHaveCount(0);
  await expect(page.locator(".next-step kbd")).toContainText("回车");
  await expect(page.getByRole("button", { name: "暂停媒体" })).toBeVisible();
  await expect(page.getByLabel("媒体播放进度")).toHaveAttribute("type", "range");
  await page.getByRole("button", { name: "暂停媒体" }).click();
  const pausedAt = await mediaTime(page);
  await page.waitForTimeout(200);
  expect(await mediaTime(page)).toBe(pausedAt);
  await page.getByLabel("媒体播放进度").fill("2");
  expect(await mediaTime(page)).toBeCloseTo(2, 1);
  await page.getByRole("button", { name: "播放媒体" }).click();
});

test("初始鼠标光标不代表零值；可在任意位置开始", async ({ page }) => {
  await open(page);
  await enterValence(page);
  await expect(
    page.locator(".initial-cursor .mouse-left-button"),
  ).toBeVisible();
  await expect(page.getByTestId("dimension-value")).toBeEmpty();
  await expect(page.locator(".mouse-hints .hold-mouse")).toHaveCount(2);
  await expect(page.locator(".mouse-hints .mouse-left-button")).toHaveCount(1);
  await expect(page.locator(".mouse-hints")).toContainText("松开暂停 Release");
  await expect(page.locator(".dimension-row.active .dimension-bar")).toHaveCSS(
    "width",
    "30px",
  );
  // 光标是圆的，而且比尺子宽——压住时仍看得见落点
  await expect(page.locator(".initial-cursor")).toHaveCSS("width", "52px");
  await expect(page.locator(".initial-cursor")).toHaveCSS("height", "52px");
  await expect(page.getByRole("button", { name: /播放媒体|暂停媒体/ })).toHaveCount(0);
  await expect(page.getByLabel("媒体播放进度")).not.toHaveAttribute("type", "range");
  await expect(page.getByLabel("播放速度")).toBeEnabled();
  await expect(page.getByRole("button", { name: "打开声音" })).toBeDisabled();
  const valenceIcons = page.locator('[data-dimension="valence"] .bar-semantics svg');
  await expect(valenceIcons).toHaveCount(2);
  await expect(valenceIcons.first()).toHaveCSS("fill", "rgb(217, 106, 102)");
  await expect(valenceIcons.last()).toHaveCSS("fill", "rgb(82, 168, 129)");
  expect(await records(page, "samples")).toHaveLength(0);
  await pressBar(page, 0.8);
  await expect(page.getByTestId("dimension-value")).toHaveText("0.60");
  await page.mouse.up();
});

test("非当前维纯灰，没有光标或数值", async ({ page }) => {
  await open(page);
  await enterValence(page);
  const inactive = page.locator(".dimension-row.inactive");
  await expect(inactive.locator(".bar-cursor, .active-value")).toHaveCount(0);
  await expect(inactive.locator(".dimension-bar")).toHaveCSS(
    "background-image",
    "none",
  );
});

test("按住延迟 0.5 秒，媒体同步暂停；右键不启动", async ({ page }) => {
  await open(page);
  await enterValence(page);
  await page
    .locator(".dimension-row.active .dimension-bar")
    .click({ button: "right" });
  expect(await records(page, "attempts")).toHaveLength(0);
  await pressBar(page);
  await page.waitForTimeout(250);
  expect(await mediaTime(page)).toBe(0);
  await expect(page.locator(".sampling-strip")).toContainText("准备中");
  await expect(page.locator(".sampling-strip")).toContainText("采样中");
  await page.mouse.up();
});

test("松手暂停，再按仍需等待；移出端点继续采样", async ({ page }) => {
  await open(page);
  await enterValence(page);
  const box = await pressBar(page);
  await expect(page.locator(".sampling-strip")).toContainText("采样中");
  // 拖到条子下方之外：纵向尺的底端是 −1
  await page.mouse.move(box.x + box.width / 2, box.y + box.height + 40);
  await expect(page.getByTestId("dimension-value")).toHaveText("-1.00");
  await page.mouse.up();
  const stopped = await mediaTime(page);
  await page.waitForTimeout(250);
  expect(await mediaTime(page)).toBe(stopped);
  await pressBar(page, 0.4);
  await page.waitForTimeout(250);
  expect(await mediaTime(page)).toBe(stopped);
  await page.mouse.up();
});

test("三页完整提交、两种渐变、固定条位置与完成筛选", async ({ page }) => {
  await open(page);
  await enterValence(page);
  const valenceBox = await page
    .locator('[data-dimension="valence"] .dimension-bar')
    .boundingBox();
  const arousalBox = await page
    .locator('[data-dimension="arousal"] .dimension-bar')
    .boundingBox();
  // 两条尺并排竖立：效价在左、唤醒在右
  expect(valenceBox!.x).toBeLessThan(arousalBox!.x);
  const nextBox = await page.locator(".next-step").boundingBox();
  const valenceGradient = await page
    .locator(".dimension-row.active .dimension-bar")
    .evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(valenceGradient).toContain("217, 106, 102");
  expect(valenceGradient).toContain("82, 168, 129");
  await expect(page.locator(".v3-navigation button")).toHaveText([
    "上一步",
    "重标",
    "下一步回车",
  ]);
  await page.getByLabel("播放速度").selectOption("1");
  await pressBar(page);
  await expect(page.locator(".next-step")).toBeEnabled({ timeout: 20000 });
  await page.mouse.up();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("唤醒 Arousal标注条")).toBeVisible();
  await page.getByRole("button", { name: "标注指南 Guide", exact: true }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("唤醒 Arousal标注条")).toBeVisible();
  await expect(page.getByLabel("播放速度")).toHaveValue("1");
  await page.getByLabel("播放速度").selectOption("0.5");
  expect(
    await page
      .locator('[data-dimension="valence"] .dimension-bar')
      .boundingBox(),
  ).toEqual(valenceBox);
  expect(
    await page
      .locator('[data-dimension="arousal"] .dimension-bar')
      .boundingBox(),
  ).toEqual(arousalBox);
  expect(await page.locator(".next-step").boundingBox()).toEqual(nextBox);
  const arousalGradient = await page
    .locator(".dimension-row.active .dimension-bar")
    .evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(arousalGradient).not.toBe(valenceGradient);
  expect(arousalGradient).toContain("244, 215, 108");
  await pressBar(page);
  await expect(page.locator(".next-step")).toBeEnabled({ timeout: 20000 });
  await page.mouse.up();
  await page.keyboard.press("Enter");
  await expect(page.locator(".workspace-heading")).toContainText("面部 2/2");
  await expect
    .poll(async () => (await records(page, "submissions")).length)
    .toBe(2);
  const attempts = await records(page, "attempts");
  const samples = await records(page, "samples");
  const valence = attempts.find((attempt) => attempt.dimension === "valence");
  const arousal = attempts.find((attempt) => attempt.dimension === "arousal");
  const timesFor = (id: string) =>
    samples
      .filter((sample) => sample.attempt_id === id)
      .sort((left, right) => left.sample_index - right.sample_index)
      .map((sample) => sample.media_time);
  expect(timesFor(valence.attempt_id)).toEqual(timesFor(arousal.attempt_id));
  expect(timesFor(valence.attempt_id)).toEqual(
    Array.from({ length: 68 }, (_, index) => index / 10),
  );
  await expect(page.locator('.task-item [aria-label="已完成"]')).toHaveCount(1);
  await page.getByRole("button", { name: "未完成 Todo", exact: true }).click();
  await expect(page.locator(".task-item")).toHaveCount(1);
  await expect(page.locator(".task-item")).toHaveText("S1-2");
  await page.getByRole("button", { name: "全部 All" }).click();
  await page.getByRole("button", { name: "S1-1" }).click();
  await expect(page.getByLabel("唤醒 Arousal标注条")).toBeVisible();
  await page.getByRole("button", { name: "重新标注当前维度 Redo" }).click();
  await expect(page.locator(".next-step")).toBeDisabled();
  expect(
    (await records(page, "attempts")).filter(
      (attempt) => attempt.dimension === "valence",
    ),
  ).toHaveLength(1);
});

test("熟悉与效价页可重开指南，回车关闭不推进、不创建标注", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "标注指南 Guide", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("面部表情");
  await page.keyboard.press("Enter");
  await expect(page.locator(".familiarization-copy")).toBeVisible();
  await enterValence(page);
  await page.getByRole("button", { name: "标注指南 Guide", exact: true }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("效价 Valence标注条")).toBeVisible();
  expect(await records(page, "attempts")).toHaveLength(0);
  expect(await mediaTime(page)).toBe(0);
});

test("标注倍速在刷新与换任务后保留，熟悉仍为 1 倍速", async ({ page }) => {
  await open(page);
  await enterValence(page);
  await page.getByLabel("播放速度").selectOption("0.7");
  await page.reload();
  await page.getByRole("button", { name: "知道了" }).click();
  await expect(page.getByLabel("播放速度")).toHaveValue("1");
  await page.locator(".next-step").click();
  await expect(page.getByLabel("播放速度")).toHaveValue("0.7");
  await page.getByLabel("播放速度").selectOption("0.3");
  await page.getByRole("button", { name: "S1-2" }).click();
  await expect(page.getByLabel("播放速度")).toHaveValue("1");
  await page.locator(".next-step").click();
  await expect(page.getByLabel("播放速度")).toHaveValue("0.3");
});

test("返回熟悉页恢复 1 倍速", async ({ page }) => {
  await open(page);
  await page.getByLabel("播放速度").selectOption("0.1");
  await page.locator(".next-step").click();
  await expect(page.getByLabel("播放速度")).toHaveValue("0.5");
  await page.getByLabel("播放速度").selectOption("1");
  await page.getByRole("button", { name: "上一步 Back" }).click();
  await expect(page.getByLabel("播放速度")).toHaveValue("1");
});

test("跨模态回车只确认指引，不推进背后的页面", async ({ page }) => {
  await open(page);
  const section = page
    .locator(".task-section")
    .filter({ has: page.getByText("S2 身体", { exact: true }) });
  await section.locator(".task-section-heading").click();
  await page.getByRole("button", { name: "S2-1" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".workspace-heading")).toContainText("身体 Body 1/2");
  await expect(page.locator(".familiarization-copy")).toBeVisible();
});

test("音频 0.1 倍速警告", async ({ page }) => {
  await open(page);
  const section = page
    .locator(".task-section")
    .filter({ has: page.getByText("S3 音频", { exact: true }) });
  await section.locator(".task-section-heading").click();
  await page.getByRole("button", { name: "S3-1" }).click();
  await page.keyboard.press("Enter");
  await expect(page.locator(".workspace-heading")).toContainText("音频 Audio");
  await page.getByLabel("播放速度").selectOption("0.1");
  await expect(page.locator(".rate-warning")).toContainText("难以听清");
  const volume = page.getByRole("button", { name: "静音" });
  await expect(volume).toBeEnabled();
  await volume.click();
  await expect(page.getByRole("button", { name: "打开声音" })).toBeEnabled();
});

test("刷新保留中断草稿，需要显式重标", async ({ page }) => {
  await open(page);
  await enterValence(page);
  await pressBar(page);
  await expect(page.locator(".sampling-strip")).toContainText("采样中");
  await page.mouse.up();
  await expect
    .poll(async () => (await records(page, "samples")).length)
    .toBeGreaterThan(0);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "重新标注当前维度 Redo" }),
  ).toBeEnabled();
  await expect(page.locator(".next-step")).toBeDisabled();
});

test("断网继续本地保存并自动补传", async ({ page, context }) => {
  await open(page);
  await enterValence(page);
  const offline = (route: Route) => route.abort("internetdisconnected");
  await page.route("**/api/**", offline);
  await context.setOffline(true);
  await pressBar(page);
  await expect(page.locator(".sampling-strip")).toContainText("采样中");
  await page.mouse.up();
  await expect
    .poll(async () => (await records(page, "samples")).length)
    .toBeGreaterThan(0);
  // 断网时界面不提示：保存与上传的状态对标注者无用，他也无能为力。
  // 只有本机都写不进去才必须说，那时继续标就是白标。
  await expect(page.locator(".operation-notice")).toHaveCount(0);
  await page.unroute("**/api/**", offline);
  await context.setOffline(false);
  // 恢复网络后自动补传，勾随之出现——勾只认云端确认过的
  await expect(page.locator(".task-item .teal-text").first()).toBeVisible({
    timeout: 20000,
  });
});

test("720px 与 390px 无横向溢出，说话人与导航可见", async ({ page }) => {
  await open(page);
  await enterValence(page);
  for (const width of [720, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBe(width);
    await expect(page.getByAltText("目标说话人 Target speaker")).toBeVisible();
    await expect(page.locator(".next-step")).toBeVisible();
  }
});
