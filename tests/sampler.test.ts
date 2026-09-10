import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizePoint, Sampler } from "../src/core/sampler";
import {
  silentWav,
  textAt,
  validateTasks,
  validateTranscript,
} from "../src/core/textTimeline";
import transcript from "../public/transcripts/demo.json";
import tasks from "../public/tasks.json";

afterEach(() => vi.useRealTimers());
describe("原始媒体时间采样", () => {
  it("映射四角、中心与区域外坐标，纵轴向上增加", () => {
    expect(normalizePoint(0, 0, 100, 100)).toEqual({ valence: -1, arousal: 1 });
    expect(normalizePoint(100, 100, 100, 100)).toEqual({
      valence: 1,
      arousal: -1,
    });
    expect(normalizePoint(50, 50, 100, 100)).toEqual({
      valence: 0,
      arousal: 0,
    });
    expect(normalizePoint(-5, 110, 100, 100)).toEqual({
      valence: -1,
      arousal: -1,
    });
  });
  it("鼠标静止仍采样，使用倍速后的实际媒体时间，不重复启动定时器", () => {
    vi.useFakeTimers();
    let time = 0;
    const record = vi.fn(),
      sampler = new Sampler(
        10,
        () => ({ time, point: { valence: 0.3, arousal: 0.7 }, playing: true }),
        record,
      );
    sampler.start();
    sampler.start();
    for (let i = 1; i <= 10; i++) {
      time = i * 0.15;
      vi.advanceTimersByTime(100);
    }
    expect(record).toHaveBeenCalledTimes(11);
    expect(record.mock.calls.at(-1)).toEqual([
      1.5,
      { valence: 0.3, arousal: 0.7 },
    ]);
    sampler.stop();
  });
  it("暂停或缓冲时不产生重复时间样本，恢复后继续，结束后停止", () => {
    vi.useFakeTimers();
    let time = 0,
      playing = true;
    const record = vi.fn(),
      sampler = new Sampler(
        10,
        () => ({ time, point: { valence: 0, arousal: 0 }, playing }),
        record,
      );
    sampler.start();
    vi.advanceTimersByTime(1000);
    expect(record).toHaveBeenCalledTimes(1);
    playing = false;
    time = 0.5;
    vi.advanceTimersByTime(300);
    expect(record).toHaveBeenCalledTimes(1);
    playing = true;
    vi.advanceTimersByTime(100);
    expect(record).toHaveBeenCalledTimes(2);
    sampler.stop();
    time = 1;
    vi.advanceTimersByTime(500);
    expect(record).toHaveBeenCalledTimes(2);
  });
});
describe("文本与任务时间轴", () => {
  it("遵守字词起点、句子结束和停顿区间，跳回起点不泄露后文", () => {
    const doc = validateTranscript(transcript, 12);
    expect(textAt(doc, 0)).toBe("");
    expect(textAt(doc, 0.5)).toBe("有时候，");
    expect(textAt(doc, 1.2)).toBe("有时候，");
    expect(textAt(doc, 3.3)).toBe("有时候，情绪很轻，却很清晰。");
    expect(textAt(doc, 4.5)).toBe("");
    expect(textAt(doc, 5)).toBe("停一停，");
    expect(textAt(doc, 12)).toBe("");
    expect(textAt(doc, 0)).toBe("");
  });
  it("拒绝重叠文本、无效时长、重复任务编号", () => {
    const doc = structuredClone(transcript);
    doc.sentences[0].tokens[1].start = 0.7;
    expect(() => validateTranscript(doc, 12)).toThrow();
    expect(() => validateTranscript(transcript, 10)).toThrow();
    expect(() => validateTasks([...tasks, tasks[0]])).toThrow();
    expect(() => validateTasks([{ ...tasks[0], duration: 0 }])).toThrow();
  });
  it("无声媒体资源具有精确的 PCM 时长并限制无效输入", async () => {
    const blob = silentWav(12),
      view = new DataView(await blob.arrayBuffer());
    expect(view.getUint32(40, true) / view.getUint32(28, true)).toBe(12);
    expect(() => silentWav(Infinity)).toThrow();
    expect(() => silentWav(3601)).toThrow();
  });
});
