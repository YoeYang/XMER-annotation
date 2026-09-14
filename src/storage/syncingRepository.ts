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
