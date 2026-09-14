import type { Attempt, ExportData, Sample, Submission } from "../types";
import type { AnnotationRepository } from "./repository";

export interface HttpOptions {
  baseUrl: string;
  getToken: () => string | null;
  fetch?: typeof fetch;
}

/** 服务器按 chunk_index 拼接采样块；用批次首个 sample_index 当序号，
 *  重试时同一批算出同一个序号，天然幂等。 */
export const chunkIndexOf = (samples: Sample[]) => samples[0].sample_index;

export class HttpRepository implements AnnotationRepository {
  private fetcher: typeof fetch;
  constructor(private options: HttpOptions) {
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  }
  private async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const token = this.options.getToken();
    if (!token) throw new Error("缺少访问令牌，请用分配给你的专属网址打开页面");
    const response = await this.fetcher(this.options.baseUrl + path, {
      ...init,
      headers: {
        ...init.headers,
        "content-type": "application/json",
        authorization: "Bearer " + token,
      },
    });
    if (!response.ok) {
      const detail = await response
        .json()
        .then((body: { detail?: string }) => body.detail)
        .catch(() => null);
      throw new Error(detail ?? "服务器保存失败（" + response.status + "）");
    }
    return response.json() as Promise<T>;
  }
  async checkpoint(attempt: Attempt, samples: Sample[]) {
    await this.request<Attempt>("/attempts/" + attempt.attempt_id, {
      method: "PUT",
      body: JSON.stringify({
        task_id: attempt.task_id,
        media_id: attempt.media_id,
        modality: attempt.modality,
        mode: attempt.mode,
        status: attempt.status,
        task_snapshot: attempt.task_snapshot,
        events: attempt.events,
        sample_rate_hz: attempt.sample_rate_hz,
        started_at: attempt.started_at,
        completed_at: attempt.completed_at,
      }),
    });
    if (!samples.length) return;
    await this.request(
      "/attempts/" + attempt.attempt_id + "/chunks/" + chunkIndexOf(samples),
      { method: "PUT", body: JSON.stringify({ samples }) },
    );
  }
  async listAttempts(_annotator: string) {
    return this.request<Attempt[]>("/attempts");
  }
  async attemptSamples(attemptId: string) {
    return this.request<Sample[]>("/attempts/" + attemptId + "/samples");
  }
  async listSubmissions(_annotator: string) {
    return this.request<Submission[]>("/submissions");
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
  /** 提交编号由调用方给定，重试必须复用同一个，否则会被当成新版本。 */
  async submitWith(attemptId: string, submissionId: string) {
    return this.request<Submission>("/attempts/" + attemptId + "/submit", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId }),
    });
  }
  async submit(attemptId: string) {
    return this.submitWith(attemptId, crypto.randomUUID());
  }
  async export(_annotator: string) {
    return this.request<ExportData>("/export");
  }
}
