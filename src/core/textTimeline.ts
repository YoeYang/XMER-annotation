import type { Task, Transcript } from "../types";
export function validateTasks(input: unknown): Task[] {
  if (!Array.isArray(input) || !input.length)
    throw new Error("任务目录为空或格式无效");
  const ids = new Set<string>();
  for (const task of input) {
    if (
      !task ||
      !["audio", "text", "face", "body", "audiovisual"].includes(
        task.modality,
      ) ||
      !["task_id", "media_id", "display_id", "src", "target"].every(
        (k) => typeof task[k] === "string" && task[k].trim(),
      ) ||
      typeof task.demo !== "boolean" ||
      task.timeline_origin !== 0 ||
      !Number.isInteger(task.order_index) ||
      task.order_index < 0 ||
      !Number.isFinite(task.duration) ||
      task.duration <= 0 ||
      ids.has(task.task_id)
    )
      throw new Error("任务配置无效：请检查编号、模态、时长和统一时间起点");
    ids.add(task.task_id);
  }
  return input;
}
export function validateTranscript(
  input: unknown,
  duration: number,
): Transcript {
  const doc = input as Transcript;
  // 容差 1 毫秒而不是严格相等：两个数各自经过一次 JSON 往返、一次
  // Python 的 round，末位差一点就会把整个文本任务锁死——曾经有 2317 个
  // 任务因为 3.718333 对 3.718 打不开，而这点差异标注上毫无意义。
  if (
    !doc ||
    !Number.isFinite(doc.duration) ||
    Math.abs(doc.duration - duration) > 0.001 ||
    !Array.isArray(doc.sentences)
  )
    throw new Error("文本时长与任务不一致");
  let previous = 0;
  for (const sentence of doc.sentences) {
    if (
      !Number.isFinite(sentence.start) ||
      !Number.isFinite(sentence.end) ||
      sentence.start < previous ||
      sentence.end <= sentence.start ||
      sentence.end > doc.duration + 0.001 ||
      !Array.isArray(sentence.tokens) ||
      !sentence.tokens.length
    )
      throw new Error("文本句子时间戳无效或重叠");
    let tokenEnd = sentence.start;
    for (const token of sentence.tokens) {
      if (
        !Number.isFinite(token.start) ||
        !Number.isFinite(token.end) ||
        token.start < tokenEnd ||
        token.end <= token.start ||
        token.end > sentence.end ||
        typeof token.text !== "string" ||
        !token.text
      )
        throw new Error("文本字词时间戳无效或重叠");
      tokenEnd = token.end;
    }
    previous = sentence.end;
  }
  return doc;
}
export interface TimedToken {
  text: string;
  /** 与上一个词之间的分隔符：中文两侧不加空格，英文加。 */
  lead: string;
  /** 播放是否已经说到这个词。整段常驻，只有这个标记随时间推进。 */
  spoken: boolean;
}
const CJK =
  /[\u2e80-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]/;
// 英文若不补空格会拼成一个超长单词，浏览器找不到断点，长句直接冲出画面。
function needsSpace(before: string, after: string): boolean {
  const a = before.slice(-1),
    b = after.slice(0, 1);
  return !!a && !!b && !CJK.test(a) && !CJK.test(b);
}
/**
 * 整段转录稿一次给全，已说到的词标 spoken。
 * 逐词浮现动得太快不好标，且句子讲完后画面会空掉——尤其片尾有长静默时。
 */
/**
 * 一律呈现**原文**，按转录稿自带的词级时间戳逐词点亮。
 *
 * 曾经改成过「中文素材一律显示 `text_en` 译文」，因为担心懂中文与不懂中文的
 * 标注者读到的东西不同。那条路已经废弃：中文样本改由懂中文的标注者标，
 * 译文转为后备。**译文还有个硬伤**——词级时间戳没法跨语言对齐，只能把整句
 * 时长均分给英文词，实测点亮位置偏差中位 0.32s、最大 5.57s，
 * 而这是个按时间连续标注的任务，点亮位置错了标出来的曲线就错了。
 *
 * 转录稿里的 `text_en` 字段保留不动，这里不再读它。
 */
export function transcriptLines(doc: Transcript, time: number) {
  return doc.sentences.map((sentence) => {
    let previous = "";
    return {
      tokens: sentence.tokens.map((token) => {
        const lead = needsSpace(previous, token.text) ? " " : "";
        previous = token.text;
        return { text: token.text, lead, spoken: token.start <= time };
      }),
    };
  });
}

export function transcriptTokens(doc: Transcript, time: number): TimedToken[] {
  const out: TimedToken[] = [];
  let previous = "";
  for (const sentence of doc.sentences)
    for (const token of sentence.tokens) {
      out.push({
        text: token.text,
        lead: needsSpace(previous, token.text) ? " " : "",
        spoken: token.start <= time,
      });
      previous = token.text;
    }
  return out;
}
// A real silent PCM media resource: the HTML audio element, not a wall clock, drives text time.
export function silentWav(duration: number): Blob {
  if (!Number.isFinite(duration) || duration <= 0 || duration > 3600)
    throw new Error("文本时长须在 0 到 3600 秒之间");
  const rate = 8000,
    count = Math.ceil(duration * rate);
  const bytes = new ArrayBuffer(44 + count),
    view = new DataView(bytes);
  const word = (offset: number, text: string) =>
    [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  word(0, "RIFF");
  view.setUint32(4, 36 + count, true);
  word(8, "WAVE");
  word(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate, true);
  view.setUint16(32, 1, true);
  view.setUint16(34, 8, true);
  word(36, "data");
  view.setUint32(40, count, true);
  new Uint8Array(bytes, 44).fill(128);
  return new Blob([bytes], { type: "audio/wav" });
}
