import type { Attempt, ExportData, Sample, Submission } from "../types";
export interface AnnotationRepository {
  checkpoint(attempt: Attempt, samples: Sample[]): Promise<void>;
  listAttempts(annotator: string): Promise<Attempt[]>;
  /** 某一维轮次的全部原始采样点，按 sample_index 排好。 */
  attemptSamples(attemptId: string): Promise<Sample[]>;
  listSubmissions(annotator: string): Promise<Submission[]>;
  recoverInterrupted(annotator: string): Promise<void>;
  submit(attemptId: string): Promise<Submission>;
  export(annotator: string): Promise<ExportData>;
}
