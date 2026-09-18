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

describe("文本一律呈现英文，按原文节奏逐词点亮", () => {
  const chinese: Transcript = {
    duration: 4,
    sentences: [
      {
        start: 1.0,
        end: 3.0,
        text_en: "Don't dream anymore, study hard.",
        tokens: [
          { start: 1.0, end: 1.5, text: "别" },
          { start: 1.6, end: 2.2, text: "做梦" },
          { start: 2.3, end: 3.0, text: "了" },
        ],
      },
    ],
  };

  it("中文素材显示译文，不显示原文", () => {
    // 并排中英的话，懂中文的读中文、不懂的读英文，两拨人的节奏与理解
    // 都不同，标出来的曲线没法放在一起比
    const words = transcriptLines(chinese, 9).flatMap((l) =>
      l.tokens.map((t) => t.text),
    );
    expect(words).toEqual(["Don't", "dream", "anymore,", "study", "hard."]);
    expect(words.join("")).not.toContain("做梦");
  });

  it("整句的起止跟着原文，句内均匀分配", () => {
    // 句子 1.0–3.0 秒共 5 个词，每词 0.4 秒
    const at = (time: number) =>
      transcriptLines(chinese, time)[0].tokens.filter((t) => t.spoken).length;
    expect(at(0.9)).toBe(0); // 整句还没开始
    expect(at(1.0)).toBe(1); // 第一个词跟着句子起点亮
    expect(at(1.9)).toBe(3); // 1.0 + 2×0.4 = 1.8 已过
    expect(at(3.0)).toBe(5); // 句末全亮
  });

  it("英文素材原样用自己的词级时间戳", () => {
    // 非 chsims 的素材本来就是英文，有真实的逐词对齐，不必打散重排
    const lines = transcriptLines(english, 1);
    expect(lines[0].tokens.length).toBeGreaterThan(0);
    expect(lines[0].tokens.some((t) => t.spoken)).toBe(true);
  });
});

describe("时长校验留 1 毫秒容差", () => {
  const doc = (duration: number): Transcript => ({
    duration,
    sentences: [
      {
        start: 0.1,
        end: 1.0,
        tokens: [{ start: 0.1, end: 1.0, text: "话" }],
      },
    ],
  });

  it("末位差异不该把整个任务锁死", () => {
    // 线上真实事故：清单写 3.718333、转录稿写 3.718，2317 个文本任务
    // 因此打不开，界面报「文本时长与任务不一致」。两个数各自经过一次
    // JSON 往返和一次 round，末位对不上是常态，而这点差异标注上毫无意义。
    expect(() => validateTranscript(doc(3.718), 3.718333)).not.toThrow();
    expect(() => validateTranscript(doc(3.7185), 3.718)).not.toThrow();
  });

  it("真正不是同一条素材时仍然拦下", () => {
    // 容差只放过末位噪声，差半秒就是拿错了文件
    expect(() => validateTranscript(doc(3.7), 4.2)).toThrow();
    expect(() => validateTranscript(doc(3.72), 3.718)).toThrow();
  });
});
