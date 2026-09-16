import { describe, expect, it } from "vitest";
import {
  buildTaskSections,
  dimensionSubmitted,
  taskComplete,
  ticketId,
} from "../src/core/taskFlow";
import type { Attempt, Dimension, Submission, Task } from "../src/types";

const task = (
  id: string,
  modality: Task["modality"],
  order_index: number,
): Task => ({
  task_id: id,
  media_id: id,
  display_id: "S0001",
  modality,
  src: "/media/example/visual.mp4",
  duration: 1.95,
  target: "目标人物",
  demo: false,
  timeline_origin: 0,
  order_index,
});

const attempt = (
  id: string,
  task_id: string,
  dimension: Dimension,
): Attempt => ({
  schema_version: 1,
  attempt_id: id,
  task_id,
  annotator_id: "P3-07",
  media_id: task_id,
  modality: "face",
  mode: "annotation",
  dimension,
  familiarization_plays: 2,
  status: "completed",
  task_snapshot: task(task_id, "face", 0),
  sample_rate_hz: 10,
  started_at: "2026-09-16T00:00:00.000Z",
  completed_at: "2026-09-16T00:00:02.000Z",
  sample_count: 20,
  last_media_time: 1.9,
  events: [],
  calibration: null,
});

const submission = (id: string, attempt_id: string): Submission => ({
  submission_id: id,
  task_id: "face-1",
  annotator_id: "P3-07",
  attempt_id,
  revision: 1,
  previous_submission_id: null,
  submitted_at: "2026-09-16T00:00:03.000Z",
  updated_at: null,
});

describe("模态 section 与块内编号", () => {
  it("按固定模态分块，并在块内按 order_index 计算 1-based 位置", () => {
    const sections = buildTaskSections([
      task("body-2", "body", 8),
      task("face-2", "face", 7),
      task("audio-1", "audio", 2),
      task("face-1", "face", 3),
    ]);
    expect(sections.map((section) => section.modality)).toEqual([
      "face",
      "body",
      "audio",
    ]);
    expect(
      sections[0].tasks.map((row) => [
        row.task.task_id,
        row.position,
        row.total,
      ]),
    ).toEqual([
      ["face-1", 1, 2],
      ["face-2", 2, 2],
    ]);
  });

  it("工单号只含标注者、模态与块内序号", () => {
    expect(ticketId("P3-07", "face", 3)).toBe("P3-07-face-03");
  });

  it("只有 valence 与 arousal 都提交才完成子任务", () => {
    const attempts = [
      attempt("valence-1", "face-1", "valence"),
      attempt("arousal-1", "face-1", "arousal"),
    ];
    const submissions = [submission("sub-v", "valence-1")];
    expect(dimensionSubmitted(attempts, submissions, "face-1", "valence")).toBe(
      true,
    );
    expect(taskComplete(attempts, submissions, "face-1")).toBe(false);
    submissions.push(submission("sub-a", "arousal-1"));
    expect(taskComplete(attempts, submissions, "face-1")).toBe(true);
  });

  it("重标后只认当前维度的最新轮次", () => {
    const oldAttempt = attempt("valence-old", "face-1", "valence");
    const newestAttempt = {
      ...attempt("valence-new", "face-1", "valence"),
      started_at: "2026-09-16T00:01:00.000Z",
    };

    expect(
      dimensionSubmitted(
        [oldAttempt, newestAttempt],
        [submission("sub-old", oldAttempt.attempt_id)],
        "face-1",
        "valence",
      ),
    ).toBe(false);
  });
});
