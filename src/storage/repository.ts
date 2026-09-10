import type { Attempt, ExportData, Sample, Submission } from "../types";
export interface AnnotationRepository {
  checkpoint(attempt: Attempt, samples: Sample[]): Promise<void>;
  listAttempts(annotator: string): Promise<Attempt[]>;
  listSubmissions(annotator: string): Promise<Submission[]>;
  recoverInterrupted(annotator: string): Promise<void>;
  submit(attemptId: string): Promise<Submission>;
  export(annotator: string): Promise<ExportData>;
}
