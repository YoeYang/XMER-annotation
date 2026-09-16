import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import { SyncingRepository } from "../src/storage/syncingRepository";
import type { HttpRepository } from "../src/storage/httpRepository";
import { makeSample } from "../src/core/sampler";
import type { Attempt, Task } from "../src/types";

const task: Task = {
  task_id: "source::body",
  media_id: "source-body",
  display_id: "S0001",
  modality: "body",
  src: "/media/example/visual.mp4",
  duration: 1.95,
  target: "目标人物",
  demo: true,
  timeline_origin: 0,
  order_index: 0,
};

function fixture(overrides: Partial<Attempt> = {}): Attempt {
  return {
    schema_version: 1,
    attempt_id: crypto.randomUUID(),
    task_id: task.task_id,
    annotator_id: "A001",
    media_id: task.media_id,
    modality: task.modality,
    mode: "annotation",
    dimension: "valence",
    familiarization_plays: 2,
    status: "completed",
    task_snapshot: task,
    sample_rate_hz: 10,
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    sample_count: 1,
    last_media_time: 0,
    events: [],
    calibration: null,
    ...overrides,
  };
}

/** 可控的假服务器：记录调用，并能按需失败。 */
function fakeRemote() {
  const calls: string[] = [];
  let failures = 0;
  return {
    calls,
    failNext: (times: number) => (failures = times),
    repository: {
      checkpoint: vi.fn(async (attempt: Attempt) => {
        if (failures-- > 0) throw new Error("网络不可达");
        calls.push("checkpoint:" + attempt.attempt_id);
      }),
      submitWith: vi.fn(async (attemptId: string, submissionId: string) => {
        if (failures-- > 0) throw new Error("网络不可达");
        calls.push("submit:" + submissionId);
        return null;
      }),
      recoverInterrupted: vi.fn(async () => {
        calls.push("recover");
      }),
      listAttempts: vi.fn(async () => {
        throw new Error("网络不可达");
      }),
      listSubmissions: vi.fn(async () => {
        throw new Error("网络不可达");
      }),
      export: vi.fn(async () => {
        throw new Error("网络不可达");
      }),
    } as unknown as HttpRepository,
  };
}

const local = () => new IndexedDbRepository("test-" + crypto.randomUUID());

describe("本地先写、后台同步", () => {
  beforeEach(() => vi.useRealTimers());

  it("断网时标注照常进行，数据已落本地且计入待上传", async () => {
    const db = local(),
      remote = fakeRemote();
    remote.failNext(99);
    const sync = new SyncingRepository(db, remote.repository, [10_000]);
    const attempt = fixture(),
      sample = makeSample({ ...attempt, sample_count: 0 }, 0, 0.2);

    await sync.checkpoint(attempt, [sample]);
    await vi.waitFor(() => expect(sync.getState().lastError).toBe("网络不可达"));

    // 服务器没收到，但本地已经存下了——这正是不丢数据的关键
    expect(remote.calls).toEqual([]);
    expect(sync.getState().pending).toBe(1);
    expect((await db.export("A001")).attempts[0].samples).toEqual([sample]);
    sync.dispose();
  });

  it("恢复连接后补传，队列排空", async () => {
    const remote = fakeRemote();
    remote.failNext(2);
    const sync = new SyncingRepository(local(), remote.repository, [1]);
    const attempt = fixture();

    await sync.checkpoint(attempt, []);
    await sync.drain();

    expect(remote.calls).toEqual(["checkpoint:" + attempt.attempt_id]);
    expect(sync.getState().pending).toBe(0);
    expect(sync.getState().lastError).toBeNull();
  });

  it("按产生顺序串行推送，不会因重试乱序", async () => {
    const remote = fakeRemote();
    const sync = new SyncingRepository(local(), remote.repository, [1]);
    const first = fixture(),
      second = fixture();

    await sync.checkpoint(first, []);
    remote.failNext(1);
    await sync.checkpoint(second, []);
    await sync.drain();

    expect(remote.calls).toEqual([
      "checkpoint:" + first.attempt_id,
      "checkpoint:" + second.attempt_id,
    ]);
  });

  it("提交复用本地编号，重试不会被服务器当成新版本", async () => {
    const db = local(),
      remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository, [1]);
    const attempt = fixture(),
      sample = makeSample({ ...attempt, sample_count: 0 }, 0, 0.1);
    await sync.checkpoint(attempt, [sample]);
    await sync.drain();

    remote.failNext(1);
    const submission = await sync.submit(attempt.attempt_id);
    await sync.drain();

    expect(remote.calls).toContain("submit:" + submission.submission_id);
    expect(
      remote.calls.filter((c) => c.startsWith("submit:")),
    ).toHaveLength(1);
  });

  it("读取时服务器不可达就回落本地，不至于打不开页面", async () => {
    const db = local(),
      remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository, [1]);
    const attempt = fixture();
    await db.checkpoint(attempt, []);

    const attempts = await sync.listAttempts("A001");
    expect(attempts.map((a) => a.attempt_id)).toEqual([attempt.attempt_id]);
    expect((await sync.export("A001")).storage).toBe("local");
  });

  it("界面能订阅待上传条数的变化", async () => {
    const remote = fakeRemote();
    remote.failNext(99);
    const sync = new SyncingRepository(local(), remote.repository, [10_000]);
    const seen: number[] = [];
    sync.subscribe((state) => seen.push(state.pending));

    await sync.checkpoint(fixture(), []);
    await vi.waitFor(() => expect(sync.getState().lastError).not.toBeNull());

    expect(seen).toContain(1);
    sync.dispose();
  });
});
