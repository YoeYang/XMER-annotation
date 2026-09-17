import "fake-indexeddb/auto";
import { describe, expect, it, vi } from "vitest";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import { SyncingRepository } from "../src/storage/syncingRepository";
import type { HttpRepository } from "../src/storage/httpRepository";
import { makeSample } from "../src/core/sampler";
import type { Attempt, Sample, Submission, Task } from "../src/types";

/**
 * 标完一个维度就上传，等它真的到了云端再继续。
 *
 * 原先是「写本机 → 把上传塞进后台队列 → 立刻返回」，然后马上去服务器
 * 重读列表——而上传还没到，于是标完了侧栏的勾不出现。人看到的就是
 * 「没保存」。现在提交要等上传回来（有超时兜底），拿到结果再刷新。
 */

const task: Task = {
  task_id: "S0312::face", media_id: "S0312-face", display_id: "S0312",
  modality: "face", src: "/pool/v3/media/S0312/face.mp4", duration: 2,
  target: "", demo: false, timeline_origin: 0, order_index: 0,
};

function fixture(dimension: "valence" | "arousal" = "valence"): Attempt {
  return {
    schema_version: 1, attempt_id: crypto.randomUUID(), task_id: task.task_id,
    annotator_id: "A001", media_id: task.media_id, modality: task.modality,
    mode: "annotation", dimension, familiarization_plays: 2,
    status: "completed", task_snapshot: task, sample_rate_hz: 10,
    started_at: new Date().toISOString(), completed_at: new Date().toISOString(),
    sample_count: 0, last_media_time: 0, events: [], calibration: null,
  };
}

function fakeRemote(
  opts: { offline?: boolean; slowMs?: number; submitFails?: boolean } = {},
) {
  const seen = { submits: [] as string[] };
  const store: Submission[] = [];
  const guard = async () => {
    if (opts.slowMs) await new Promise((r) => setTimeout(r, opts.slowMs));
    if (opts.offline) throw new Error("网络不可达");
  };
  return {
    seen, store,
    repository: {
      checkpoint: vi.fn(guard),
      submitWith: vi.fn(async (attemptId: string, submissionId: string) => {
        await guard();
        if (opts.submitFails) throw new Error("提交没送到");
        seen.submits.push(submissionId);
        const row = { submission_id: submissionId, task_id: task.task_id,
          annotator_id: "A001", attempt_id: attemptId, dimension: "valence",
          revision: 1, previous_submission_id: null,
          submitted_at: new Date().toISOString(), updated_at: null } as unknown as Submission;
        store.push(row);
        return row;
      }),
      listSubmissions: vi.fn(async () => { await guard(); return store; }),
      listAttempts: vi.fn(async () => { await guard(); return []; }),
      attemptSamples: vi.fn(async () => { await guard(); return [] as Sample[]; }),
      recoverInterrupted: vi.fn(guard),
      export: vi.fn(guard),
    } as unknown as HttpRepository,
  };
}

const local = () => new IndexedDbRepository("up-" + crypto.randomUUID());

async function record(db: IndexedDbRepository, attempt: Attempt) {
  const samples = [0, 1, 2].map((i) =>
    makeSample({ ...attempt, sample_count: i }, i * 0.1, 0.5),
  );
  attempt.sample_count = samples.length;
  await db.checkpoint(attempt, samples);
}

describe("标完一个维度立刻上传", () => {
  it("提交返回时，上传已经到了服务器", async () => {
    const db = local(), remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);

    const result = await sync.submit(attempt.attempt_id);

    // 提交刚返回就该能在服务器那边看到——不必再等队列
    expect(remote.seen.submits).toContain(result.submission_id);
    expect(sync.getState().pending).toBe(0);
  });

  it("上传成功时 synced 为真，界面据此说「已上传」", async () => {
    const db = local(), remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);

    expect(await sync.submitSynced(attempt.attempt_id)).toBe(true);
  });

  it("断网时不卡着人：如实回报没上传成功，数据留在本机等补传", async () => {
    const db = local(), remote = fakeRemote({ offline: true });
    const sync = new SyncingRepository(db, remote.repository, [10_000]);
    const attempt = fixture();
    await record(db, attempt);

    expect(await sync.submitSynced(attempt.attempt_id, 200)).toBe(false);
    expect(sync.getState().pending).toBeGreaterThan(0);
    expect((await db.listSubmissions("A001")).length).toBe(1);
  });

  it("上传慢到超时也不卡：超时返回假，后台继续传", async () => {
    const db = local(), remote = fakeRemote({ slowMs: 400 });
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);

    expect(await sync.submitSynced(attempt.attempt_id, 50)).toBe(false);
    await sync.drain();
    expect(remote.seen.submits.length).toBe(1);
  });
});

describe("列表取本机与云端的并集", () => {
  it("云端可达但这条还没传上去，本机有就得算数", async () => {
    // 这才是「标完了勾不出现」的真实场景：服务器在线、列表读得到，
    // 只是这一条的提交还没送达。若只认云端，界面就会否认人刚做完的事。
    const db = local(), remote = fakeRemote({ submitFails: true });
    const sync = new SyncingRepository(db, remote.repository, [10_000]);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submitSynced(attempt.attempt_id, 100);

    const rows = await sync.listSubmissions("A001");
    expect(rows.map((r) => r.attempt_id)).toContain(attempt.attempt_id);
  });

  it("断网时也一样认本机的", async () => {
    const db = local(), remote = fakeRemote({ offline: true });
    const sync = new SyncingRepository(db, remote.repository, [10_000]);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submitSynced(attempt.attempt_id, 100);

    const rows = await sync.listSubmissions("A001");
    expect(rows.map((r) => r.attempt_id)).toContain(attempt.attempt_id);
  });

  it("同一条两边都有时不重复", async () => {
    const db = local(), remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submit(attempt.attempt_id);

    const rows = await sync.listSubmissions("A001");
    const ids = rows.map((r) => r.submission_id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
