import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import { makeSample } from "../src/core/sampler";
import type { Attempt, Dimension, Task } from "../src/types";

const task: Task = {
  task_id: "source::face",
  annotator_id: undefined,
  media_id: "source-face",
  display_id: "S0001",
  modality: "face",
  src: "/media/example/visual.mp4",
  duration: 1.95,
  target: "目标人物",
  demo: true,
  timeline_origin: 0,
  order_index: 0,
} as Task;

function fixture(dimension: Dimension = "valence"): Attempt {
  return {
    schema_version: 1,
    attempt_id: crypto.randomUUID(),
    task_id: task.task_id,
    annotator_id: "A001",
    media_id: task.media_id,
    modality: task.modality,
    mode: "annotation",
    dimension,
    familiarization_plays: 1.3,
    status: "completed",
    task_snapshot: task,
    sample_rate_hz: 10,
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    sample_count: 1,
    last_media_time: 0,
    events: [],
    calibration: null,
  };
}

const repo = () => new IndexedDbRepository("test-" + crypto.randomUUID());

describe("V3 本地持久化与分维版本", () => {
  it("草稿可读，重复保存去重且拒绝篡改单值原始样本", async () => {
    const db = repo();
    const attempt = fixture();
    const sample = makeSample({ ...attempt, sample_count: 0 }, 0, 0.2);
    await db.checkpoint(attempt, [sample]);
    await db.checkpoint(attempt, [sample]);
    expect((await db.export("A001")).attempts[0].samples).toEqual([sample]);
    await expect(
      db.checkpoint(attempt, [{ ...sample, value: 0.8 }]),
    ).rejects.toThrow();
    expect((await db.export("A001")).attempts[0].samples[0].value).toBe(0.2);
  });

  it("按轮次读回采样点并隔离不同轮次", async () => {
    const db = repo();
    const a = fixture();
    const b = fixture("arousal");
    const sample = (attempt: Attempt, index: number) =>
      makeSample({ ...attempt, sample_count: index }, index * 0.1, index / 10);
    await db.checkpoint(
      { ...a, sample_count: 3 },
      [sample(a, 2), sample(a, 0)],
    );
    await db.checkpoint({ ...b, sample_count: 1 }, [sample(b, 0)]);
    const rows = await db.attemptSamples(a.attempt_id);
    expect(rows.map((row) => row.sample_index)).toEqual([0, 2]);
    expect(rows.every((row) => row.attempt_id === a.attempt_id)).toBe(true);
    expect(await db.attemptSamples("missing")).toEqual([]);
  });

  it("两个维度各自维护版本链，重复提交仍幂等", async () => {
    const db = repo();
    const firstValence = fixture("valence");
    await db.checkpoint(firstValence, [
      makeSample({ ...firstValence, sample_count: 0 }, 0, 0),
    ]);
    const [first, duplicate] = await Promise.all([
      db.submit(firstValence.attempt_id),
      db.submit(firstValence.attempt_id),
    ]);
    expect(duplicate).toEqual(first);
    expect(first.revision).toBe(1);

    const arousal = fixture("arousal");
    await db.checkpoint(arousal, [
      makeSample({ ...arousal, sample_count: 0 }, 0, 0.4),
    ]);
    const arousalSubmission = await db.submit(arousal.attempt_id);
    expect(arousalSubmission.revision).toBe(1);
    expect(arousalSubmission.previous_submission_id).toBeNull();

    const secondValence = fixture("valence");
    await db.checkpoint(secondValence, [
      makeSample({ ...secondValence, sample_count: 0 }, 0, 0.5),
    ]);
    const update = await db.submit(secondValence.attempt_id);
    expect(update.revision).toBe(2);
    expect(update.previous_submission_id).toBe(first.submission_id);
    expect(update.submitted_at).toBe(first.submitted_at);
    expect(update.updated_at).not.toBeNull();
  });

  it("恢复中断记录而不伪造完成", async () => {
    const db = repo();
    const attempt = {
      ...fixture(),
      status: "recording" as const,
      completed_at: null,
      sample_count: 0,
    };
    await db.checkpoint(attempt, []);
    await db.recoverInterrupted("A001");
    expect((await db.listAttempts("A001"))[0].status).toBe("interrupted");
    expect((await db.listAttempts("A001"))[0].completed_at).toBeNull();
    expect(await db.listAttempts("A002")).toHaveLength(0);
    await expect(db.submit(attempt.attempt_id)).rejects.toThrow("只能提交");
  });

  it("拒绝采样点尚未完整保存的轮次", async () => {
    const db = repo();
    const attempt = fixture();
    await db.checkpoint(attempt, []);
    await expect(db.submit(attempt.attempt_id)).rejects.toThrow("尚未完整");
  });
});
