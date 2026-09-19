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

/** 已完成的子任务数。两个维度都提交才算一条。 */
export function completedCount(
  tasks: Task[],
  attempts: Attempt[],
  submissions: Submission[],
) {
  return tasks.filter((task) => taskComplete(attempts, submissions, task.task_id))
    .length;
}

/**
 * 队列是否全部标完，用来决定弹不弹收尾页。
 *
 * **空队列不算完成**：素材还没下发时 `tasks` 是空的，
 * 「每一条都完成了」在空集上恒真，会在刚登录、什么都没标的时候撒花。
 */
export function allComplete(
  tasks: Task[],
  attempts: Attempt[],
  submissions: Submission[],
) {
  return tasks.length > 0 && completedCount(tasks, attempts, submissions) === tasks.length;
}

export function orderedTasks(tasks: Task[]) {
  return buildTaskSections(tasks).flatMap((section) =>
    section.tasks.map((row) => row.task),
  );
}
