import type { Attempt, Dimension, Modality, Submission, Task } from "../types";

export const MODALITY_ORDER: Modality[] = [
  "face",
  "body",
  "audio",
  "text",
  "audiovisual",
];

export interface TaskLocation {
  task: Task;
  position: number;
  total: number;
}

export interface TaskSection {
  modality: Modality;
  tasks: TaskLocation[];
}

export function buildTaskSections(tasks: Task[]): TaskSection[] {
  return MODALITY_ORDER.map((modality) => {
    const rows = tasks
      .filter((task) => task.modality === modality)
      .slice()
      .sort((a, b) => a.order_index - b.order_index);
    return {
      modality,
      tasks: rows.map((task, index) => ({
        task,
        position: index + 1,
        total: rows.length,
      })),
    };
  }).filter((section) => section.tasks.length > 0);
}

export function locationOf(tasks: Task[], taskId: string) {
  for (const section of buildTaskSections(tasks)) {
    const location = section.tasks.find((row) => row.task.task_id === taskId);
    if (location) return location;
  }
  return null;
}

export function ticketId(
  annotator: string,
  modality: Modality,
  position: number,
) {
  return `${annotator}-${modality}-${String(position).padStart(2, "0")}`;
}

export function latestAttempt(
  attempts: Attempt[],
  taskId: string,
  dimension: Dimension,
) {
  return attempts
    .filter(
      (attempt) =>
        attempt.task_id === taskId && attempt.dimension === dimension,
    )
    .sort((a, b) => a.started_at.localeCompare(b.started_at))
    .at(-1);
}

export function dimensionSubmitted(
  attempts: Attempt[],
  submissions: Submission[],
  taskId: string,
  dimension: Dimension,
) {
  const current = latestAttempt(attempts, taskId, dimension);
  return (
    !!current &&
    submissions.some(
      (submission) => submission.attempt_id === current.attempt_id,
    )
  );
}

export function taskComplete(
  attempts: Attempt[],
  submissions: Submission[],
  taskId: string,
) {
  return (
    dimensionSubmitted(attempts, submissions, taskId, "valence") &&
    dimensionSubmitted(attempts, submissions, taskId, "arousal")
  );
}

export function orderedTasks(tasks: Task[]) {
  return buildTaskSections(tasks).flatMap((section) =>
    section.tasks.map((row) => row.task),
  );
}
