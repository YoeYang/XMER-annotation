import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizeValue, Sampler } from "../src/core/sampler";
import {
  silentWav,
  transcriptLines,
  transcriptTokens,
  validateTasks,
  validateTranscript,
} from "../src/core/textTimeline";
import type { Task, Transcript } from "../src/types";
import transcript from "../public/transcripts/demo.json";
import tasks from "../public/tasks.json";

const validTask = {
  ...tasks[1],
  modality: "audio",
  order_index: 0,
} as Task;

afterEach(() => vi.useRealTimers());
/** 相邻点的间隔去重后的集合，用来断言栅格是否整齐 */
const record_spacing = (times: number[]) => [
  ...new Set(times.slice(1).map((t, i) => +(t - times[i]).toFixed(10))),
];
describe("原始媒体时间采样", () => {
  it("把横向位置映射到单维值，并将滑出区域的指针钳在端点", () => {
    expect(normalizeValue(0, 100)).toBe(-1);
    expect(normalizeValue(100, 100)).toBe(1);
    expect(normalizeValue(50, 100)).toBe(0);
    expect(normalizeValue(-5, 100)).toBe(-1);
    expect(normalizeValue(110, 100)).toBe(1);
  });
  /**
   * 按倍速播放一段媒体：墙上时钟每 25ms 推进一次，媒体时间按 rate 前进。
   * mediaSeconds 刻意取格点之间的值（如 1.95），否则末点是否被收进来
   * 要看浮点误差，断言会变得不稳。
   */
  const play = (rate: number, mediaSeconds: number) => {
    let time = 0;
    const record = vi.fn(),
      sampler = new Sampler(
        10,
        () => ({ time, value: 0.3, playing: true }),
        record,
      );
    sampler.start();
    while (time < mediaSeconds) {
      time = Math.min(time + (25 * rate) / 1000, mediaSeconds);
      vi.advanceTimersByTime(25);
    }
    sampler.stop();
    return record;
  };

  it("采样密度只由媒体时间决定，与播放倍速无关", () => {
    // 采样若挂在墙上时钟上，0.5 倍速会采出两倍的点，
    // 不同倍速标出来的曲线时间栅格对不齐，没法直接比较。
    vi.useFakeTimers();
    for (const rate of [0.1, 0.3, 0.5, 0.7, 1]) {
      const record = play(rate, 1.95);
      const times = record.mock.calls.map((c) => c[0]);
      expect(times.length, `倍速 ${rate}`).toBe(20);
      expect(times.slice(0, 4), `倍速 ${rate}`).toEqual([0, 0.1, 0.2, 0.3]);
      expect(times.at(-1), `倍速 ${rate}`).toBeCloseTo(1.9, 10);
    }
  });

  it("点落在统一的 0.1 秒栅格上，倍速不同也能逐点对齐", () => {
    vi.useFakeTimers();
    const slow = play(0.1, 0.95).mock.calls.map((c) => c[0]);
    const fast = play(1, 0.95).mock.calls.map((c) => c[0]);
    expect(slow).toEqual(fast);
    expect(record_spacing(slow)).toEqual([0.1]);
  });

  it("鼠标静止仍持续采样，不重复启动定时器", () => {
    vi.useFakeTimers();
    let time = 0;
    const record = vi.fn(),
      sampler = new Sampler(
        10,
        () => ({ time, value: 0.3, playing: true }),
        record,
      );
    sampler.start();
    sampler.start();
    for (let i = 1; i <= 39; i++) {
      time = i * 0.025;
      vi.advanceTimersByTime(25);
    }
    expect(record).toHaveBeenCalledTimes(10);
    expect(record.mock.calls.at(-1)).toEqual([0.9, 0.3]);
    sampler.stop();
  });
  it("暂停或缓冲时不产生重复时间样本，恢复后继续，结束后停止", () => {
    vi.useFakeTimers();
    let time = 0,
      playing = true;
    const record = vi.fn(),
      sampler = new Sampler(10, () => ({ time, value: 0, playing }), record);
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
    for (const t of [0, 0.5, 4.5, 11.9, 12, 99])
      expect(line(doc, t)).toBe(full);
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
    expect(() => validateTasks([validTask, validTask])).toThrow();
    expect(() => validateTasks([{ ...validTask, duration: 0 }])).toThrow();
  });
  it("无声媒体资源具有精确的 PCM 时长并限制无效输入", async () => {
    const blob = silentWav(12),
      view = new DataView(await blob.arrayBuffer());
    expect(view.getUint32(40, true) / view.getUint32(28, true)).toBe(12);
    expect(() => silentWav(Infinity)).toThrow();
    expect(() => silentWav(3601)).toThrow();
  });
});

describe("中英并排：中文逐词、英文整句", () => {
  const bilingual: Transcript = {
    duration: 4,
    sentences: [
      {
        start: 0.1,
        end: 1.5,
        text_en: "Don't dream anymore, study hard.",
        tokens: [
          { start: 0.1, end: 0.4, text: "别" },
          { start: 0.5, end: 0.8, text: "做梦" },
          { start: 0.9, end: 1.5, text: "了" },
        ],
      },
      {
        start: 2.0,
        end: 3.5,
        text_en: "At least all will turn.",
        tokens: [
          { start: 2.0, end: 2.6, text: "至少" },
          { start: 2.7, end: 3.5, text: "都会转" },
        ],
      },
    ],
  };

  it("译文按句挂着，不切成词", () => {
    // 中英词序不同，逐词对齐做不到；硬对齐会把译文切成看不懂的碎片
    const lines = transcriptLines(bilingual, 0);
    expect(lines).toHaveLength(2);
    expect(lines[0].english).toBe("Don't dream anymore, study hard.");
    expect(lines[0].tokens).toHaveLength(3);
  });

  it("中文逐词点亮，英文跟着本句首词一起亮", () => {
    const lines = transcriptLines(bilingual, 0.6);
    expect(lines[0].tokens.map((t) => t.spoken)).toEqual([true, true, false]);
    expect(lines[0].spoken).toBe(true);
    // 第二句还没到，整句连同译文都不亮
    expect(lines[1].spoken).toBe(false);
    expect(lines[1].tokens.every((t) => !t.spoken)).toBe(true);
  });

  it("没有译文的转录稿照常渲染", () => {
    // 非 chsims 的素材本来就是英文，没有 text_en 字段
    const lines = transcriptLines(english, 1);
    expect(lines[0].english).toBe("");
    expect(lines[0].tokens.length).toBeGreaterThan(0);
  });
});
