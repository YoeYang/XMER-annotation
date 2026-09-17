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
  let offline = opts.offline ?? false;
  const guard = async () => {
    if (opts.slowMs) await new Promise((r) => setTimeout(r, opts.slowMs));
    if (offline) throw new Error("网络不可达");
  };
  return {
    seen, store,
    goOffline: () => (offline = true),
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
  it("提交不等上传，本机一落库就返回", async () => {
    // 等一次网络往返会让「下一步」明显卡一下，标一条卡一次。
    // 上传进度交给云端状态条显示，不挡着人往下走。
    const db = local(), remote = fakeRemote({ slowMs: 300 });
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);

    const started = Date.now();
    await sync.submit(attempt.attempt_id);
    expect(Date.now() - started).toBeLessThan(200);

    // 上传确实在后台进行
    await sync.drain();
    expect(remote.seen.submits.length).toBe(1);
  });
});

describe("勾只认云端：本机存下不算完成", () => {
  it("上传还没成功时，这条不算已提交", async () => {
    // 勾是对标注者的承诺：这条标完了、存住了。云端没有却打勾，
    // 就是假承诺——人以为做完了，数据其实只躺在自己浏览器里。
    const db = local(), remote = fakeRemote({ submitFails: true });
    const sync = new SyncingRepository(db, remote.repository, [10_000]);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submit(attempt.attempt_id);

    const rows = await sync.listSubmissions("A001");
    expect(rows.map((r) => r.attempt_id)).not.toContain(attempt.attempt_id);
  });

  it("上传成功后，这条才算已提交", async () => {
    const db = local(), remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submit(attempt.attempt_id);
    await sync.drain();

    const rows = await sync.listSubmissions("A001");
    expect(rows.map((r) => r.attempt_id)).toContain(attempt.attempt_id);
  });

  it("断网时宁可不显示，也不拿本机的充数", async () => {
    const db = local(), remote = fakeRemote({ offline: true });
    const sync = new SyncingRepository(db, remote.repository, [10_000]);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submit(attempt.attempt_id);

    expect(await sync.listSubmissions("A001")).toEqual([]);
  });

  it("断网前读到过的，断网后仍照原样显示", async () => {
    // 已经确认在云端的那些不该因为一次网络抖动就消失
    const db = local(), remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);
    await sync.submit(attempt.attempt_id);
    await sync.drain();
    await sync.listSubmissions("A001");

    remote.goOffline();
    const rows = await sync.listSubmissions("A001");
    expect(rows.map((r) => r.attempt_id)).toContain(attempt.attempt_id);
  });

  it("上传成功会通知订阅者，界面据此把勾补上", async () => {
    const db = local(), remote = fakeRemote({ slowMs: 100 });
    const sync = new SyncingRepository(db, remote.repository);
    const attempt = fixture();
    await record(db, attempt);

    const settled: number[] = [];
    sync.subscribe((state) => settled.push(state.pending));
    await sync.submit(attempt.attempt_id);
    await sync.drain();

    expect(settled).toContain(0);
  });
});
