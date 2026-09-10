import type { Task, Transcript } from "../types";
export function validateTasks(input: unknown): Task[] {
  if (!Array.isArray(input) || !input.length)
    throw new Error("任务目录为空或格式无效");
  const ids = new Set<string>();
  for (const task of input) {
    if (
      !task ||
      !["visual", "audio", "text", "audiovisual"].includes(task.modality) ||
      !["task_id", "media_id", "source_id", "title", "src", "target"].every(
        (k) => typeof task[k] === "string" && task[k].trim(),
      ) ||
      typeof task.demo !== "boolean" ||
      task.timeline_origin !== 0 ||
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
  if (!doc || doc.duration !== duration || !Array.isArray(doc.sentences))
    throw new Error("文本时长与任务不一致");
  let previous = 0;
  for (const sentence of doc.sentences) {
    if (
      !Number.isFinite(sentence.start) ||
      !Number.isFinite(sentence.end) ||
      sentence.start < previous ||
      sentence.end <= sentence.start ||
      sentence.end > duration ||
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
export function textAt(doc: Transcript, time: number): string {
  const sentence = doc.sentences.find((s) => time >= s.start && time < s.end);
  return sentence
    ? sentence.tokens
        .filter((t) => t.start <= time)
        .map((t) => t.text)
        .join("")
    : "";
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
