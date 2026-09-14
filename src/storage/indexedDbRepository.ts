import type { Attempt, ExportData, Sample, Submission } from "../types";
import type { AnnotationRepository } from "./repository";

const request = <T>(req: IDBRequest<T>) =>
  new Promise<T>((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
const done = (tx: IDBTransaction) =>
  new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error ?? new Error("本地保存事务中断"));
    tx.onerror = () => reject(tx.error ?? new Error("本地保存失败"));
  });
export class IndexedDbRepository implements AnnotationRepository {
  private database: Promise<IDBDatabase>;
  constructor(name = "xmer-annotation-v1") {
    this.database = new Promise((resolve, reject) => {
      const req = indexedDB.open(name, 1);
      req.onupgradeneeded = () => {
        req.result.createObjectStore("attempts", { keyPath: "attempt_id" });
        const samples = req.result.createObjectStore("samples", {
          keyPath: ["attempt_id", "sample_index"],
        });
        samples.createIndex("attempt", "attempt_id");
        const submissions = req.result.createObjectStore("submissions", {
          keyPath: "submission_id",
        });
        submissions.createIndex("attempt", "attempt_id", { unique: true });
      };
      req.onsuccess = () => {
        req.result.onversionchange = () => req.result.close();
        resolve(req.result);
      };
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error("请关闭其他旧版本页面后重试"));
    });
    // Consumers receive errors through repository calls, without an unhandled rejection at startup.
    void this.database.catch(() => {});
  }
  async checkpoint(attempt: Attempt, samples: Sample[]) {
    const db = await this.database,
      tx = db.transaction(["attempts", "samples"], "readwrite");
    const completion = done(tx);
    const meta = tx.objectStore("attempts");
    const existing = meta.get(attempt.attempt_id);
    existing.onsuccess = () => {
      const old = existing.result as Attempt | undefined;
      if (
        old &&
        (old.sample_count > attempt.sample_count ||
          (["completed", "interrupted"].includes(old.status) &&
            JSON.stringify(old) !== JSON.stringify(attempt)))
      ) {
        tx.abort();
        return;
      }
      meta.put(attempt);
      for (const sample of samples) {
        const store = tx.objectStore("samples");
        const lookup = store.get([sample.attempt_id, sample.sample_index]);
        lookup.onsuccess = () => {
          if (
            sample.attempt_id !== attempt.attempt_id ||
            sample.sample_index >= attempt.sample_count ||
            (lookup.result &&
              JSON.stringify(lookup.result) !== JSON.stringify(sample))
          ) {
            tx.abort();
            return;
          }
          if (!lookup.result) store.add(sample);
        };
      }
    };
    await completion;
  }
  private async readAll<T>(store: string): Promise<T[]> {
    const db = await this.database;
    return request(
      db.transaction(store).objectStore(store).getAll(),
    ) as Promise<T[]>;
  }
  async listAttempts(annotator: string) {
    return (await this.readAll<Attempt>("attempts"))
      .filter((a) => a.annotator_id === annotator)
      .sort((a, b) => a.started_at.localeCompare(b.started_at));
  }
  async attemptSamples(attemptId: string): Promise<Sample[]> {
    const db = await this.database;
    const rows: Sample[] = await request(
      db
        .transaction("samples")
        .objectStore("samples")
        .index("attempt")
        .getAll(attemptId),
    );
    return rows.sort((a, b) => a.sample_index - b.sample_index);
  }
  async listSubmissions(annotator: string) {
    return (await this.readAll<Submission>("submissions"))
      .filter((s) => s.annotator_id === annotator)
      .sort((a, b) => a.revision - b.revision);
  }
  async recoverInterrupted(annotator: string) {
    for (const attempt of await this.listAttempts(annotator)) {
      if (attempt.status === "recording" || attempt.status === "paused") {
        attempt.status = "interrupted";
        attempt.events.push({
          index: attempt.events.length,
          type: "recovered_after_interruption",
          media_time: attempt.last_media_time,
          wall_time: new Date().toISOString(),
          playback_rate: 1,
        });
        await this.checkpoint(attempt, []);
      }
    }
  }
  async submit(attemptId: string): Promise<Submission> {
    const db = await this.database;
    const tx = db.transaction(
        ["attempts", "submissions", "samples"],
        "readwrite",
      ),
      completion = done(tx);
    // Attach a rejection handler before validation so transaction failure never leaks.
    void completion.catch(() => {});
    try {
      const attempt: Attempt | undefined = await request(
        tx.objectStore("attempts").get(attemptId),
      );
      if (
        !attempt ||
        attempt.mode !== "annotation" ||
        attempt.status !== "completed" ||
        !attempt.sample_count
      )
        throw new Error("只能提交完整的正式标注轮次");
      const count = await request(
        tx.objectStore("samples").index("attempt").count(attemptId),
      );
      if (count !== attempt.sample_count)
        throw new Error("采样数据尚未完整保存，请重试保存");
      const store = tx.objectStore("submissions");
      const existing: Submission | undefined = await request(
        store.index("attempt").get(attemptId),
      );
      if (existing) {
        await completion;
        return existing;
      }
      const history = ((await request(store.getAll())) as Submission[])
        .filter(
          (s) =>
            s.annotator_id === attempt.annotator_id &&
            s.task_id === attempt.task_id,
        )
        .sort((a, b) => b.revision - a.revision);
      const previous = history[0],
        now = new Date().toISOString();
      const result: Submission = {
        submission_id: crypto.randomUUID(),
        task_id: attempt.task_id,
        annotator_id: attempt.annotator_id,
        attempt_id: attemptId,
        revision: (previous?.revision ?? 0) + 1,
        previous_submission_id: previous?.submission_id ?? null,
        submitted_at: previous?.submitted_at ?? now,
        updated_at: previous ? now : null,
      };
      store.add(result);
      await completion;
      return result;
    } catch (error) {
      try {
        tx.abort();
      } catch {
        /* Transaction may already have completed. */
      }
      throw error;
    }
  }
  async export(annotator: string): Promise<ExportData> {
    const db = await this.database,
      attempts = await this.listAttempts(annotator);
    const records = [];
    for (const attempt of attempts) {
      const samples: Sample[] = await request(
        db
          .transaction("samples")
          .objectStore("samples")
          .index("attempt")
          .getAll(attempt.attempt_id),
      );
      records.push({ ...attempt, samples });
    }
    return {
      schema_version: 1,
      exported_at: new Date().toISOString(),
      storage: "local",
      annotator_id: annotator,
      unsaved_attempt_ids: [],
      attempts: records,
      submissions: await this.listSubmissions(annotator),
    };
  }
}
