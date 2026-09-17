import "fake-indexeddb/auto";
import { describe, expect, it, vi } from "vitest";
import { IndexedDbRepository } from "../src/storage/indexedDbRepository";
import {
  SyncingRepository,
  missingRuns,
} from "../src/storage/syncingRepository";
import type { HttpRepository } from "../src/storage/httpRepository";
import { makeSample } from "../src/core/sampler";
import type { Attempt, Sample, Submission, Task } from "../src/types";

/**
 * 登录时补发卡在本机的提交。
 *
 * 标完一条本来就立刻同步，网断了也会自动重试——但那份"待重试"的清单
 * 只活在内存里。标完点保存、恰好断网、再把浏览器关掉，清单就没了，
 * 那条标注从此躺在本机而服务器不知道，直到最后汇总才发现少了一条。
 */

const task: Task = {
  task_id: "S0001::face",
  media_id: "S0001-face",
  display_id: "S0001",
  modality: "face",
  src: "/pool/v3/media/S0001/face.mp4",
  duration: 2.0,
  target: "目标人物",
  demo: false,
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
    sample_count: 0,
    last_media_time: 0,
    events: [],
    calibration: null,
    ...overrides,
  };
}

/** 假服务器：记下收到了什么，并能装作从没见过某些轮次。 */
function fakeRemote(
  known: Submission[] = [],
  samples: Sample[] = [],
  offline = false,
) {
  const got = {
    checkpoints: [] as { attempt: string; samples: Sample[] }[],
    submits: [] as string[],
  };
  const guard = () => {
    if (offline) throw new Error("网络不可达");
  };
  return {
    got,
    repository: {
      checkpoint: vi.fn(async (attempt: Attempt, batch: Sample[]) => {
        guard();
        got.checkpoints.push({ attempt: attempt.attempt_id, samples: batch });
      }),
      submitWith: vi.fn(async (_attemptId: string, submissionId: string) => {
        got.submits.push(submissionId);
        return null;
      }),
      attemptSamples: vi.fn(async () => samples),
      listSubmissions: vi.fn(async () => {
        guard();
        return known;
      }),
      listAttempts: vi.fn(async () => []),
      recoverInterrupted: vi.fn(async () => undefined),
      export: vi.fn(async () => {
        throw new Error("用不到");
      }),
    } as unknown as HttpRepository,
  };
}

const local = () => new IndexedDbRepository("resync-" + crypto.randomUUID());

/** 在本机造一条标完并已提交、但服务器毫不知情的记录。 */
async function strandLocally(db: IndexedDbRepository, points: number) {
  const attempt = fixture();
  const samples = Array.from({ length: points }, (_, i) =>
    makeSample({ ...attempt, sample_count: i }, i * 0.1, 0.5),
  );
  // sample_count 必须先长到采样点数：checkpoint 会拒收
  // sample_index >= sample_count 的点（防止把没记进轮次的点偷偷塞进来）
  attempt.sample_count = points;
  attempt.last_media_time = (points - 1) * 0.1;
  await db.checkpoint(attempt, samples);
  const submission = await db.submit(attempt.attempt_id);
  return { attempt, samples, submission };
}

describe("登录时补发卡住的提交", () => {
  it("本机有、服务器没有的，补发过去", async () => {
    const db = local();
    const { attempt, submission } = await strandLocally(db, 3);
    const remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);

    const sent = await sync.resyncSubmitted("A001");

    expect(sent).toBe(1);
    expect(remote.got.submits).toEqual([submission.submission_id]);
    expect(remote.got.checkpoints[0].attempt).toBe(attempt.attempt_id);
  });

  it("沿用本机那个提交编号，服务器才认得出是同一次提交", async () => {
    const db = local();
    const { submission } = await strandLocally(db, 2);
    const remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);

    await sync.resyncSubmitted("A001");

    expect(remote.got.submits[0]).toBe(submission.submission_id);
  });

  it("服务器已经有了的，一条都不重发", async () => {
    const db = local();
    const { submission } = await strandLocally(db, 2);
    const remote = fakeRemote([submission]);
    const sync = new SyncingRepository(db, remote.repository);

    expect(await sync.resyncSubmitted("A001")).toBe(0);
    expect(remote.got.submits).toEqual([]);
  });

  it("采样点也一并补上", async () => {
    const db = local();
    const { samples } = await strandLocally(db, 5);
    const remote = fakeRemote();
    const sync = new SyncingRepository(db, remote.repository);

    await sync.resyncSubmitted("A001");

    const sent = remote.got.checkpoints.flatMap((c) => c.samples);
    expect(sent.map((s) => s.sample_index)).toEqual(
      samples.map((s) => s.sample_index),
    );
  });

  it("服务器已收到一半时，只补缺的那半，不制造重复", async () => {
    const db = local();
    const { samples } = await strandLocally(db, 6);
    const remote = fakeRemote([], samples.slice(0, 3));
    const sync = new SyncingRepository(db, remote.repository);

    await sync.resyncSubmitted("A001");

    const sent = remote.got.checkpoints.flatMap((c) => c.samples);
    expect(sent.map((s) => s.sample_index)).toEqual([3, 4, 5]);
  });

  it("补发失败不该让人连页面都进不去", async () => {
    const db = local();
    await strandLocally(db, 2);
    const remote = fakeRemote([], [], true);
    const sync = new SyncingRepository(db, remote.repository);

    await expect(sync.resyncSubmitted("A001")).rejects.toThrow();
    // App 那边用 .catch(() => 0) 兜住，数据留在本机等下次登录
  });
});

describe("算出服务器缺哪些采样点", () => {
  const point = (index: number): Sample => ({
    task_id: task.task_id,
    annotator_id: "A001",
    modality: task.modality,
    media_id: task.media_id,
    attempt_id: "att-1",
    sample_index: index,
    media_time: index * 0.1,
    wall_time: new Date(0).toISOString(),
    value: 0.5,
    is_valid: true,
  });

  it("服务器什么都没有时，整条就是一段", () => {
    const mine = [0, 1, 2].map(point);
    expect(missingRuns(mine, [])).toEqual([mine]);
  });

  it("服务器全都有时，没有要补的", () => {
    const mine = [0, 1, 2].map(point);
    expect(missingRuns(mine, mine)).toEqual([]);
  });

  it("中间缺一段，就只补那一段", () => {
    const mine = [0, 1, 2, 3, 4].map(point);
    const theirs = [0, 1, 4].map(point);
    expect(missingRuns(mine, theirs)).toEqual([[point(2), point(3)]]);
  });

  it("缺的不连续时切成多段，各自落位", () => {
    const mine = [0, 1, 2, 3, 4, 5].map(point);
    const theirs = [1, 4].map(point);
    expect(missingRuns(mine, theirs)).toEqual([
      [point(0)],
      [point(2), point(3)],
      [point(5)],
    ]);
  });

  it("本机的顺序乱了也照样切对", () => {
    const mine = [3, 0, 2, 1].map(point);
    expect(missingRuns(mine, [])).toEqual([
      [point(0), point(1), point(2), point(3)],
    ]);
  });
});
