import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HOLD_START_DELAY_MS } from "../src/config";
import { AnnotationSession } from "../src/core/session";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import type { Task } from "../src/types";

class Media extends EventTarget {
  duration = 1.95;
  private mediaTime = 0;
  paused = true;
  seeking = false;
  readyState = 4;
  playbackRate = 1;
  ended = false;
  get currentTime() {
    return this.mediaTime;
  }
  set currentTime(value: number) {
    const isReset = value === 0 && this.mediaTime !== 0;
    this.mediaTime = value;
    if (isReset) {
      this.seeking = true;
      this.dispatchEvent(new Event("seeking"));
      this.seeking = false;
      this.dispatchEvent(new Event("seeked"));
    }
  }
  play = vi.fn(async () => {
    this.paused = false;
    this.dispatchEvent(new Event("playing"));
  });
  pause() {
    if (!this.paused) {
      this.paused = true;
      this.dispatchEvent(new Event("pause"));
    }
  }
  finish() {
    this.currentTime = this.duration;
    this.ended = true;
    this.paused = true;
    this.dispatchEvent(new Event("ended"));
  }
}

const task: Task = {
  task_id: "source::face",
  media_id: "source-face",
  display_id: "S0001",
  modality: "face",
  src: "/media/example/visual.mp4",
  duration: 1.95,
  target: "目标人物",
  demo: true,
  timeline_origin: 0,
  order_index: 0,
};

let sessions: AnnotationSession[] = [];
beforeEach(() => {
  const rates = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => rates.get(key) ?? null,
    setItem: (key: string, value: string) => rates.set(key, value),
  });
  vi.stubGlobal(
    "document",
    Object.assign(new EventTarget(), { hidden: false }),
  );
  vi.stubGlobal("window", new EventTarget());
});
afterEach(() => {
  vi.useRealTimers();
  for (const session of sessions) session.dispose();
  sessions = [];
  vi.unstubAllGlobals();
});

function setup() {
  const repository = new IndexedDbRepository("session-" + crypto.randomUUID());
  const session = new AnnotationSession(task, "A001", repository);
  const media = new Media();
  sessions.push(session);
  session.attach(media as unknown as HTMLMediaElement);
  return { session, media, repository };
}

describe("V3 按住标注会话", () => {
  it("熟悉页可暂停、继续和拖动，进入标注页后拒绝这些控制", async () => {
    const { session, media } = setup();
    await session.startFamiliarization();
    expect(media.paused).toBe(false);
    await session.toggleFamiliarization();
    expect(media.paused).toBe(true);
    session.seekFamiliarization(1.2);
    expect(media.currentTime).toBe(1.2);
    await session.toggleFamiliarization();
    expect(media.paused).toBe(false);
    await session.prepareDimension("valence", 0.6);
    session.seekFamiliarization(1.5);
    expect(media.currentTime).toBe(0);
    expect(await session.toggleFamiliarization()).toBe(false);
    expect(media.paused).toBe(true);
  });

  it("熟悉默认 1 倍速，标注默认 0.5，用户选择跨维度和会话记忆", async () => {
    const { session, media } = setup();
    session.setRate(0.1);
    await session.startFamiliarization();
    expect(session.view.rate).toBe(1);
    expect(media.playbackRate).toBe(1);

    session.setRate(0.1);
    await session.prepareDimension("valence", 0.4);
    expect(session.view.rate).toBe(0.5);
    expect(media.playbackRate).toBe(0.5);

    session.setRate(0.7);
    await session.prepareDimension("arousal", 0.4);
    expect(session.view.rate).toBe(0.7);
    expect(media.playbackRate).toBe(0.7);
    const next = setup();
    await next.session.prepareDimension("valence", 0);
    expect(next.session.view.rate).toBe(0.7);
    next.session.setRate(0.3);
    await next.session.startFamiliarization();
    expect(next.session.view.rate).toBe(1);
    await next.session.prepareDimension("valence", 0);
    expect(next.session.view.rate).toBe(0.3);
  });

  it("每次按下都等待 0.5 秒，延迟期间媒体保持暂停且不采样", async () => {
    vi.useFakeTimers();
    const { session, media } = setup();
    await session.prepareDimension("valence", 1.25);

    session.press(0.4);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS - 1);
    expect(media.play).not.toHaveBeenCalled();
    expect(media.paused).toBe(true);
    expect(session.view.attempt).toBeNull();

    await vi.advanceTimersByTimeAsync(1);
    expect(media.play).toHaveBeenCalledTimes(1);
    expect(session.view.attempt?.sample_count).toBe(1);
    expect(session.view.attempt?.dimension).toBe("valence");
    expect(session.view.attempt?.familiarization_plays).toBe(1.25);

    session.releaseHold();
    session.press(0.2);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS - 1);
    expect(media.play).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(media.play).toHaveBeenCalledTimes(2);
  });

  it("延迟期间松手会取消启动", async () => {
    vi.useFakeTimers();
    const { session, media } = setup();
    await session.prepareDimension("arousal", 0.3);
    session.press(-0.4);
    session.releaseHold();
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS);
    expect(media.play).not.toHaveBeenCalled();
    expect(session.view.attempt).toBeNull();
    expect(session.view.phase).toBe("ready");
  });

it("实时轨迹跟着采样长出来，上传后仍然完整", async () => {
    // 轨迹不能用 pending 画——那是待上传队列，checkpoint 成功后会被清掉，
    // 拿它画图会看到曲线一段段消失
    const { session, media, repository } = setup();
    await repository.listAttempts("A001");
    vi.useFakeTimers();
    await session.prepareDimension("valence", 2);
    session.press(0.5);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS);
    for (let cell = 1; cell <= 12; cell++) {
      media.currentTime = cell * 0.1 + 0.01;
      await vi.advanceTimersByTimeAsync(25);
    }
    vi.useRealTimers();
    session.releaseHold();

    const before = session.view.trace.length;
    expect(before).toBeGreaterThan(5);
    await session.flush();
    expect(session.view.trace.length).toBe(before);
    expect(session.view.trace[0]).toHaveProperty("t");
    expect(session.view.trace[0]).toHaveProperty("v");
  });

  it("换维度清空轨迹：上一维的线不能留在图上", async () => {
    const { session, media, repository } = setup();
    await repository.listAttempts("A001");
    vi.useFakeTimers();
    await session.prepareDimension("valence", 2);
    session.press(0.5);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS);
    for (let cell = 1; cell <= 5; cell++) {
      media.currentTime = cell * 0.1 + 0.01;
      await vi.advanceTimersByTimeAsync(25);
    }
    vi.useRealTimers();
    session.releaseHold();
    expect(session.view.trace.length).toBeGreaterThan(0);

    await session.prepareDimension("arousal", 2);
    expect(session.view.trace).toEqual([]);
  });

    it("松手暂停媒体，再次按住从同一媒体时刻继续且栅格无空洞", async () => {
    const { session, media, repository } = setup();
    await repository.listAttempts("A001");
    vi.useFakeTimers();
    await session.prepareDimension("valence", 2);
    session.press(-0.2);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS);

    for (let cell = 1; cell <= 3; cell++) {
      media.currentTime = cell * 0.1 + 0.01;
      await vi.advanceTimersByTimeAsync(25);
    }
    vi.useRealTimers();
    session.releaseHold();
    await session.flush();
    const stoppedAt = media.currentTime;
    vi.useFakeTimers();
    await vi.advanceTimersByTimeAsync(1000);
    expect(media.currentTime).toBe(stoppedAt);

    session.press(0.7);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS);
    for (let cell = 4; cell <= 8; cell++) {
      media.currentTime = cell * 0.1 + 0.01;
      await vi.advanceTimersByTimeAsync(25);
    }
    vi.useRealTimers();
    session.releaseHold();
    await session.flush();

    const attempt = session.view.attempt!;
    const samples = await repository.attemptSamples(attempt.attempt_id);
    expect(samples.map((sample) => sample.media_time)).toEqual(
      Array.from({ length: 9 }, (_, index) => index / 10),
    );
    expect(samples.slice(0, 4).every((sample) => sample.value === -0.2)).toBe(
      true,
    );
    expect(samples.slice(4).every((sample) => sample.value === 0.7)).toBe(true);
  });

  it("熟悉页自动循环并上报包含当前播放比例的真实次数", async () => {
    const { session, media } = setup();
    expect(await session.startFamiliarization()).toBe(true);
    media.finish();
    media.ended = false;
    media.currentTime = media.duration * 0.3;
    const plays = await session.finishFamiliarization();
    expect(plays).toBeCloseTo(1.3);
    expect(await session.startFamiliarization()).toBe(true);
    media.currentTime = media.duration * 0.2;
    expect(await session.finishFamiliarization()).toBeCloseTo(1.5);
  });

  it("后台隐藏会像松手一样暂停并保留轮次", async () => {
    vi.useFakeTimers();
    const { session, media } = setup();
    await session.prepareDimension("arousal", 2);
    session.press(0);
    await vi.advanceTimersByTimeAsync(HOLD_START_DELAY_MS);
    Object.assign(document, { hidden: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(media.paused).toBe(true);
    expect(session.view.phase).toBe("paused");
    expect(
      session.view.attempt?.events.some(
        (event) => event.type === "page_hidden",
      ),
    ).toBe(true);
  });

  it("拒绝时长不一致的素材", async () => {
    const { session, media } = setup();
    media.duration = 3;
    media.dispatchEvent(new Event("loadedmetadata"));
    expect(session.view.phase).toBe("error");
  });
});
