export type Modality = "visual" | "audio" | "text" | "audiovisual";
export interface Task {
  task_id: string;
  media_id: string;
  // 样本的不透明编号（S0001…）。同一样本的四个任务共用一个，
  // 目录与标题都只显示它：原始编号带着数据集名字，会透露样本来源。
  display_id: string;
  modality: Modality;
  src: string;
  duration: number;
  target: string;
  demo: boolean;
  timeline_origin: number;
  // 说话人身份参考，由预处理流水线产出；属任务说明，不是被评定的材料
  speaker_ref_src?: string | null;
  speaker_name?: string | null;
}
export interface Segment {
  start: number;
  end: number;
  text: string;
}
export interface Transcript {
  duration: number;
  sentences: { start: number; end: number; tokens: Segment[] }[];
}
export interface Point {
  valence: number;
  arousal: number;
}
export interface Sample extends Point {
  task_id: string;
  annotator_id: string;
  modality: Modality;
  media_id: string;
  attempt_id: string;
  sample_index: number;
  media_time: number;
  wall_time: string;
  is_valid: boolean;
}
export interface SessionEvent {
  index: number;
  type: string;
  media_time: number;
  wall_time: string;
  playback_rate: number;
}
export type AttemptStatus =
  "recording" | "paused" | "completed" | "interrupted";
export interface Attempt {
  schema_version: 1;
  attempt_id: string;
  task_id: string;
  annotator_id: string;
  media_id: string;
  modality: Modality;
  mode: "preview" | "annotation";
  status: AttemptStatus;
  task_snapshot: Task;
  sample_rate_hz: number;
  started_at: string;
  completed_at: string | null;
  sample_count: number;
  last_media_time: number;
  events: SessionEvent[];
  calibration: null;
}
export interface Submission {
  submission_id: string;
  task_id: string;
  annotator_id: string;
  attempt_id: string;
  revision: number;
  previous_submission_id: string | null;
  submitted_at: string;
  updated_at: string | null;
}
export interface ExportData {
  schema_version: 1;
  exported_at: string;
  storage: "local" | "cloud";
  annotator_id: string;
  unsaved_attempt_ids: string[];
  attempts: (Attempt & { samples: Sample[] })[];
  submissions: Submission[];
}
export type Phase =
  | "loading"
  | "ready"
  | "starting"
  | "preview"
  | "recording"
  | "paused"
  | "buffering"
  | "completed"
  | "error";
export interface SessionView {
  phase: Phase;
  time: number;
  duration: number;
  rate: number;
  point: Point | null;
  attempt: Attempt | null;
  save: "idle" | "saving" | "saved" | "error";
  savedAt: string | null;
  error: string | null;
  saveError: string | null;
}
