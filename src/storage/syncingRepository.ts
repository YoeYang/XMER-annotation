import type { Attempt, ExportData, Sample, Submission } from "../types";
import type { HttpRepository } from "./httpRepository";
import type { AnnotationRepository } from "./repository";

export interface SyncState {
  /** 尚未推送到服务器的任务数。 */
  pending: number;
  syncing: boolean;
  lastError: string | null;
  lastSyncedAt: string | null;
}

const DEFAULT_RETRY_MS = [1000, 2000, 5000, 15000, 30000];

/**
 * 本机有、服务器没有的采样点，切成连续的几段。
 *
 * 不能把整条采样当一块推上去：服务器按「块内第一个序号」给每块编号，
 * 而它那边可能已经存着按别的边界切好的块。整条推过去会和已有的块
 * 撞上编号被忽略，后半截就悄悄丢了；分段推则每段各自落位，
 * 已经到过的点一个都不会重复。
 */
export function missingRuns(mine: Sample[], theirs: Sample[]): Sample[][] {
  const arrived = new Set(theirs.map((row) => row.sample_index));
  const runs: Sample[][] = [];
  let run: Sample[] = [];
  for (const sample of [...mine].sort(
    (a, b) => a.sample_index - b.sample_index,
  )) {
    if (arrived.has(sample.sample_index)) {
      if (run.length) runs.push(run);
      run = [];
      continue;
    }
    if (run.length && sample.sample_index !== run[run.length - 1].sample_index + 1) {
      runs.push(run);
      run = [];
    }
    run.push(sample);
  }
  if (run.length) runs.push(run);
  return runs;
}

/**
 * 本地先写、后台同步。
 *
 * 标注数据先落 IndexedDB 再入队推送，断网期间标注照常进行，恢复后补传；
 * 队列串行且失败原地重试，保证到达顺序与产生顺序一致。
 */
export class SyncingRepository implements AnnotationRepository {
  private queue: (() => Promise<void>)[] = [];
  private running = false;
  private failures = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private listeners = new Set<(state: SyncState) => void>();
  private state: SyncState = {
    pending: 0,
    syncing: false,
    lastError: null,
    lastSyncedAt: null,
  };
  constructor(
    private local: AnnotationRepository,
    private remote: HttpRepository,
    private retryMs: number[] = DEFAULT_RETRY_MS,
  ) {}

  getState() {
    return { ...this.state };
  }
  subscribe(listener: (state: SyncState) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  private emit() {
    this.state.pending = this.queue.length;
    const snapshot = this.getState();
    for (const listener of this.listeners) listener(snapshot);
  }
  private enqueue(job: () => Promise<void>) {
    this.queue.push(job);
    this.emit();
    void this.run();
  }
  private async run(): Promise<void> {
    if (this.running) return;
    const job = this.queue[0];
    if (!job) return;
    this.running = true;
    this.state.syncing = true;
    this.emit();
    try {
      await job();
      this.queue.shift();
      this.failures = 0;
      this.state.lastError = null;
      this.state.lastSyncedAt = new Date().toISOString();
    } catch (error) {
      // 失败的任务留在队首，数据不丢；退避后重试
      this.failures++;
      this.state.lastError =
        error instanceof Error ? error.message : "同步到服务器失败";
      const delay =
        this.retryMs[Math.min(this.failures - 1, this.retryMs.length - 1)];
      this.timer = setTimeout(() => void this.run(), delay);
    } finally {
      this.running = false;
      this.state.syncing = false;
      this.emit();
    }
    if (!this.failures) void this.run();
  }
  /** 立即重试队首任务，用于界面上的「重试」按钮。 */
  retryNow() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.failures = 0;
    void this.run();
  }
  /** 停止重试并断开订阅；队列中的数据仍在本地，下次打开会继续补传。 */
  dispose() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.listeners.clear();
  }
  /** 等待队列排空；失败仍在重试时不会返回。 */
  drain(): Promise<void> {
    if (!this.queue.length) return Promise.resolve();
    return new Promise((resolve) => {
      const stop = this.subscribe((state) => {
        if (!state.pending) {
          stop();
          resolve();
        }
      });
    });
  }

  async checkpoint(attempt: Attempt, samples: Sample[]) {
    // 先落本地：即使服务器不可达，这一步成功就不会丢数据
    await this.local.checkpoint(attempt, samples);
    const snapshot = structuredClone(attempt),
      batch = samples.slice();
    this.enqueue(() => this.remote.checkpoint(snapshot, batch));
  }
  async submit(attemptId: string) {
    const submission = await this.local.submit(attemptId);
    // 复用本地生成的编号，重试时服务器视作同一次提交
    this.enqueue(async () => {
      await this.remote.submitWith(attemptId, submission.submission_id);
    });
    return submission;
  }
  async recoverInterrupted(annotator: string) {
    await this.local.recoverInterrupted(annotator);
    this.enqueue(() => this.remote.recoverInterrupted(annotator));
  }

  /**
   * 补发卡在本机、始终没到服务器的提交。
   *
   * 正常情况下标完一条就立刻同步，网断了也会自动重试——但那份"待重试"
   * 的清单只活在内存里。标完点保存、恰好断网、再把浏览器关掉，清单就没了，
   * 那条标注从此躺在本机，服务器永远不知道它存在，直到最后汇总时才发现
   * 少了一条，而那时已经说不清是谁的哪一条。
   *
   * 所以每次登录先核对一遍：本机已提交、服务器却没有的，补发过去。
   * **只管已提交的**——标到一半的重标一次就是了，管它反而要处理
   * "断点续标"那一大堆麻烦事。
   *
   * 重发是安全的：沿用本机那个提交编号，服务器认得出是同一次提交。
   */
  async resyncSubmitted(annotator: string): Promise<number> {
    const [mine, theirs] = await Promise.all([
      this.local.listSubmissions(annotator),
      this.remote.listSubmissions(annotator),
    ]);
    const arrived = new Set(theirs.map((row) => row.attempt_id));
    const stranded = mine.filter((row) => !arrived.has(row.attempt_id));
    if (!stranded.length) return 0;

    const attempts = new Map(
      (await this.local.listAttempts(annotator)).map((row) => [
        row.attempt_id,
        row,
      ]),
    );

    let sent = 0;
    for (const submission of stranded) {
      const attempt = attempts.get(submission.attempt_id);
      // 本机连轮次都没有，无从补起——这条只能作废，硬造一条假的更糟
      if (!attempt) continue;
      // 轮次本身先过去（幂等写入），否则服务器不认这个 attempt_id
      await this.remote.checkpoint(attempt, []);
      const samples = await this.local.attemptSamples(attempt.attempt_id);
      for (const run of missingRuns(
        samples,
        await this.remote.attemptSamples(attempt.attempt_id),
      )) {
        await this.remote.checkpoint(attempt, run);
      }
      await this.remote.submitWith(
        attempt.attempt_id,
        submission.submission_id,
      );
      sent += 1;
    }
    return sent;
  }
  /** 读优先服务器（跨设备恢复），不可达时回落本地。 */
  private async preferRemote<T>(
    remote: () => Promise<T>,
    local: () => Promise<T>,
  ): Promise<T> {
    try {
      return await remote();
    } catch {
      return local();
    }
  }
  async listAttempts(annotator: string) {
    return this.preferRemote(
      () => this.remote.listAttempts(annotator),
      () => this.local.listAttempts(annotator),
    );
  }
  async listSubmissions(annotator: string) {
    return this.preferRemote(
      () => this.remote.listSubmissions(annotator),
      () => this.local.listSubmissions(annotator),
    );
  }
  async attemptSamples(attemptId: string) {
    return this.preferRemote(
      () => this.remote.attemptSamples(attemptId),
      () => this.local.attemptSamples(attemptId),
    );
  }
  async export(annotator: string): Promise<ExportData> {
    return this.preferRemote(
      () => this.remote.export(annotator),
      () => this.local.export(annotator),
    );
  }
}
