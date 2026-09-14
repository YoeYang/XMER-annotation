import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizePoint, Sampler } from "../src/core/sampler";
import {
  silentWav,
  transcriptTokens,
  validateTasks,
  validateTranscript,
} from "../src/core/textTimeline";
import type { Transcript } from "../src/types";
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
// 整段常驻 + 高亮当前进度。渲染成一行，以及「已说到」的那一截。
const line = (doc: Transcript, time: number) =>
  transcriptTokens(doc, time)
    .map((t) => t.lead + t.text)
    .join("");
const said = (doc: Transcript, time: number) =>
  transcriptTokens(doc, time)
    .filter((t) => t.spoken)
    .map((t) => t.lead + t.text)
    .join("")
    .trimStart();

// meld_dia923_utt2：英文长句，曾经拼成一个超长单词撑破画面
const english: Transcript = {
  duration: 6.101,
  sentences: [
    {
      start: 0.3,
      end: 1.26,
      tokens: [
        { start: 0.3, end: 0.7, text: "I" },
        { start: 0.8, end: 1.26, text: "know!" },
      ],
    },
    {
      start: 1.32,
      end: 2.4,
      tokens: [
        { start: 1.32, end: 1.8, text: "And" },
        { start: 1.9, end: 2.4, text: "Im" },
      ],
    },
  ],
};

describe("文本与任务时间轴", () => {
  it("整段文字自始至终都在，只有高亮随播放推进", () => {
    const doc = validateTranscript(transcript, 12);
    const full =
      "有时候，情绪很轻，却很清晰。停一停，感受此刻的变化。让你的感知，随时间留下记录。";
    // 未开口、句间停顿、播完之后，整段都必须完整呈现——空屏是 V2 的 bug
    for (const t of [0, 0.5, 4.5, 11.9, 12, 99]) expect(line(doc, t)).toBe(full);
    expect(said(doc, 0)).toBe("");
    expect(said(doc, 0.5)).toBe("有时候，");
    expect(said(doc, 1.2)).toBe("有时候，");
    expect(said(doc, 3.3)).toBe("有时候，情绪很轻，却很清晰。");
    // 句间停顿不再清空高亮，上一句留在原地
    expect(said(doc, 4.5)).toBe("有时候，情绪很轻，却很清晰。");
    expect(said(doc, 12)).toBe(full);
    expect(said(doc, 0)).toBe("");
  });
  it("英文词间补空格、中文不补，长句才能换行", () => {
    expect(line(english, 0)).toBe("I know! And Im");
    expect(said(english, 1.35)).toBe("I know! And");
    // 中文逐字之间不得出现空格
    expect(line(validateTranscript(transcript, 12), 0)).not.toContain(" ");
  });
  it("最后一句远早于片尾结束时，文字仍然留在画面上", () => {
    // meld_dia762_utt2：片长 4.71s，末句 2.35s 就说完了
    const doc: Transcript = { ...english, duration: 4.714 };
    expect(line(doc, 4.7)).toBe("I know! And Im");
    expect(said(doc, 4.7)).toBe("I know! And Im");
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
