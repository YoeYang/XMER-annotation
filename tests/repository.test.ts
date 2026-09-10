import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import { makeSample } from "../src/core/sampler";
import type { Attempt, Task } from "../src/types";
import tasks from "../public/tasks.json";
function fixture(): Attempt {
  return {
    schema_version: 1,
    attempt_id: crypto.randomUUID(),
    task_id: "DEMO-001",
    annotator_id: "A001",
    media_id: "demo-visual",
    modality: "visual",
    mode: "annotation",
    status: "completed",
    task_snapshot: tasks[0] as Task,
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
describe("本地持久化与提交版本", () => {
  it("草稿可重新读取，重复保存去重且拒绝篡改历史原始样本", async () => {
    const db = repo(),
      attempt = fixture(),
      sample = makeSample({ ...attempt, sample_count: 0 }, 0, {
        valence: 0.2,
        arousal: 0.4,
      });
    await db.checkpoint(attempt, [sample]);
    await db.checkpoint(attempt, [sample]);
    expect((await db.export("A001")).attempts[0].samples).toEqual([sample]);
    await expect(
      db.checkpoint(attempt, [{ ...sample, valence: 0.8 }]),
    ).rejects.toThrow();
    expect((await db.export("A001")).attempts[0].samples[0].valence).toBe(0.2);
  });
  it("首次 Submit、第二次 Update、重复点击及并发请求保留唯一版本", async () => {
    const db = repo(),
      first = fixture();
    await db.checkpoint(first, [
      makeSample({ ...first, sample_count: 0 }, 0, { valence: 0, arousal: 0 }),
    ]);
    const [a, b] = await Promise.all([
      db.submit(first.attempt_id),
      db.submit(first.attempt_id),
    ]);
    expect(a).toEqual(b);
    expect(a.revision).toBe(1);
    expect(a.updated_at).toBeNull();
    const second = fixture();
    await db.checkpoint(second, [
      makeSample({ ...second, sample_count: 0 }, 0, {
        valence: 0.5,
        arousal: 0,
      }),
    ]);
    const update = await db.submit(second.attempt_id);
    expect(update.revision).toBe(2);
    expect(update.previous_submission_id).toBe(a.submission_id);
    expect(update.submitted_at).toBe(a.submitted_at);
    expect(update.updated_at).not.toBeNull();
    const data = await db.export("A001");
    expect(data.attempts).toHaveLength(2);
    expect(data.submissions).toHaveLength(2);
    expect(
      data.attempts.find((x) => x.attempt_id === first.attempt_id)?.samples[0]
        .valence,
    ).toBe(0);
  });
  it("恢复中断记录而非伪造完成，标注者读取相互区分", async () => {
    const db = repo(),
      attempt = {
        ...fixture(),
        status: "recording" as const,
        completed_at: null,
      };
    await db.checkpoint(attempt, []);
    await db.recoverInterrupted("A001");
    expect((await db.listAttempts("A001"))[0].status).toBe("interrupted");
    expect((await db.listAttempts("A001"))[0].completed_at).toBeNull();
    expect(await db.listAttempts("A002")).toHaveLength(0);
    await expect(db.submit(attempt.attempt_id)).rejects.toThrow("只能提交");
  });
  it("拒绝样本未完整保存的轮次与预览轮次", async () => {
    const db = repo(),
      attempt = fixture();
    await db.checkpoint(attempt, []);
    await expect(db.submit(attempt.attempt_id)).rejects.toThrow("尚未完整");
    const preview = { ...fixture(), mode: "preview" as const };
    await db.checkpoint(preview, []);
    await expect(db.submit(preview.attempt_id)).rejects.toThrow("只能提交");
  });
});
