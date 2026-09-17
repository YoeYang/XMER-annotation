import type { Attempt, ExportData, Sample, Submission } from "../types";
export interface AnnotationRepository {
  checkpoint(attempt: Attempt, samples: Sample[]): Promise<void>;
  listAttempts(annotator: string): Promise<Attempt[]>;
  /** 某一维轮次的全部原始采样点，按 sample_index 排好。 */
  attemptSamples(attemptId: string): Promise<Sample[]>;
  listSubmissions(annotator: string): Promise<Submission[]>;
  recoverInterrupted(annotator: string): Promise<void>;
  submit(attemptId: string): Promise<Submission>;
  /**
   * 提交并等它真的上传成功，返回是否送达。
   *
   * 只写本机的实现（离线库、测试替身）直接返回 true——对它们而言
   * "落库"就是终点，没有"送达"这回事。
   */
  submitSynced?(attemptId: string, timeoutMs?: number): Promise<boolean>;
  export(annotator: string): Promise<ExportData>;
}
