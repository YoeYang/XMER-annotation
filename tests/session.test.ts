import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnnotationSession } from "../src/core/session";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import type { Task } from "../src/types";
import tasks from "../public/tasks.json";

class Media extends EventTarget {
  duration = 12;
  currentTime = 0;
  paused = true;
  seeking = false;
  readyState = 4;
  playbackRate = 1;
  ended = false;
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
    this.currentTime = 12;
    this.ended = true;
    this.paused = true;
    this.dispatchEvent(new Event("ended"));
  }
}
let sessions: AnnotationSession[] = [];
beforeEach(() => {
  vi.stubGlobal(
    "document",
    Object.assign(new EventTarget(), { hidden: false }),
  );
  vi.stubGlobal("window", new EventTarget());
});
afterEach(async () => {
  for (const s of sessions) {
    s.dispose();
    await s.flush();
  }
  sessions = [];
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function setup() {
  const repository = new IndexedDbRepository("session-" + crypto.randomUUID());
  const session = new AnnotationSession(tasks[0] as Task, "A001", repository),
    media = new Media();
  sessions.push(session);
  session.attach(media as unknown as HTMLMediaElement);
  return { session, media, repository };
}
describe("完整标注轮次状态", () => {
  it("首次点击从零记录，重复开始只有一次，完成自动保存且可 Submit", async () => {
    const { session, media, repository } = setup();
    const first = session.start("annotation", { valence: 0.3, arousal: 0.5 });
    await session.start("annotation", { valence: 0.8, arousal: 0.2 });
    await first;
    expect(media.play).toHaveBeenCalledTimes(1);
    expect(session.view.attempt?.sample_count).toBe(1);
    media.finish();
    await session.flush();
    const data = await repository.export("A001");
    expect(data.attempts).toHaveLength(1);
    expect(data.attempts[0].samples.map((s) => s.media_time)).toEqual([0, 12]);
    expect(data.attempts[0].completed_at).not.toBeNull();
    expect(
      (await repository.submit(data.attempts[0].attempt_id)).revision,
    ).toBe(1);
  });
  it("暂停、后台、缓冲停止采样，保留控制事件与实际倍速", async () => {
    const { session, media } = setup();
    await session.start("annotation", { valence: 0, arousal: 0 });
    session.setRate(1.5);
    expect(media.playbackRate).toBe(1.5);
    media.dispatchEvent(new Event("waiting"));
    expect(session.view.phase).toBe("buffering");
    media.dispatchEvent(new Event("playing"));
    expect(session.view.phase).toBe("recording");
    Object.assign(document, { hidden: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(session.view.phase).toBe("paused");
    expect(media.paused).toBe(true);
    expect(
      session.view.attempt?.events.some((e) => e.type === "page_hidden"),
    ).toBe(true);
    Object.assign(document, { hidden: false });
    await session.resume();
    expect(session.view.phase).toBe("recording");
  });
  it("预览不采样，开始正式轮次不覆盖预览记录", async () => {
    const { session, repository } = setup();
    await session.start("preview");
    expect(session.view.attempt?.sample_count).toBe(0);
    await session.start("annotation", { valence: 1, arousal: -1 });
    await session.flush();
    const data = await repository.export("A001");
    expect(data.attempts).toHaveLength(2);
    expect(data.attempts[0].mode).toBe("preview");
    expect(data.attempts[0].status).toBe("interrupted");
    expect(data.attempts[1].mode).toBe("annotation");
  });
  it("保存失败保留待写样本，重试不会丢失或重复", async () => {
    const { session, repository } = setup();
    const spy = vi
      .spyOn(repository, "checkpoint")
      .mockRejectedValue(new Error("quota"));
    await session.start("annotation", { valence: 0.1, arousal: 0.2 });
    await expect(session.flush()).rejects.toThrow("quota");
    expect(session.view.save).toBe("error");
    spy.mockRestore();
    await session.flush();
    expect(session.view.save).toBe("saved");
    expect((await repository.export("A001")).attempts[0].samples).toHaveLength(
      1,
    );
  });
  it("加载失败与无效时长有明确错误，不能启动", async () => {
    const { session, media } = setup();
    media.duration = NaN;
    media.dispatchEvent(new Event("loadedmetadata"));
    expect(session.view.phase).toBe("error");
    await session.start("annotation", { valence: 0, arousal: 0 });
    expect(media.play).not.toHaveBeenCalled();
  });
  it("保存持续失败时仍可导出内存中的原始尾部，并标记尚未落盘", async () => {
    const { session, media, repository } = setup();
    await session.start("annotation", { valence: 0.2, arousal: 0.3 });
    await session.flush();
    const spy = vi
      .spyOn(repository, "checkpoint")
      .mockRejectedValue(new Error("quota"));
    media.finish();
    await expect(session.flush()).rejects.toThrow("quota");
    const exported = await session.exportData();
    expect(exported.attempts[0].samples.map((s) => s.media_time)).toEqual([
      0, 12,
    ]);
    expect(exported.unsaved_attempt_ids).toEqual([
      session.view.attempt!.attempt_id,
    ]);
    expect((await repository.export("A001")).attempts[0].samples).toHaveLength(
      1,
    );
    spy.mockRestore();
    await session.flush();
  });
  it("播放器尚在开始过程中时阻止切换样本，避免遗留异步轮次", async () => {
    const { session } = setup();
    const starting = session.start("annotation", { valence: 0, arousal: 0 });
    await expect(session.leave()).rejects.toThrow("开始");
    await starting;
  });
});
