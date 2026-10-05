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

/**
 * 两个维度的最新一轮都已提交的子任务，一次遍历算完（2026-10-05）。
 *
 * 结果与对每条任务调 taskComplete 完全一样（同一任务同一维度取 started_at 最晚、
 * 并列取后出现的那轮），但不再是「每条任务都把全部轮次和提交扫一遍」——一个人标到
 * 两千条时那要几千万次运算，主线程一卡就是零点几秒，采样器跟着漏格。
 */
export function completedTaskIds(
  attempts: Attempt[],
  submissions: Submission[],
): Set<string> {
  const latest = new Map<string, Attempt>();
  for (const attempt of attempts) {
    const key = attempt.task_id + "\u0000" + attempt.dimension;
    const current = latest.get(key);
    if (!current || attempt.started_at.localeCompare(current.started_at) >= 0)
      latest.set(key, attempt);
  }
  const submitted = new Set(submissions.map((row) => row.attempt_id));
  const halves = new Map<string, number>();
  for (const attempt of latest.values()) {
    if (!submitted.has(attempt.attempt_id)) continue;
    if (attempt.dimension !== "valence" && attempt.dimension !== "arousal") continue;
    halves.set(attempt.task_id, (halves.get(attempt.task_id) ?? 0) + 1);
  }
  return new Set([...halves].filter(([, n]) => n === 2).map(([id]) => id));
}

/** 已完成的子任务数。两个维度都提交才算一条。 */
export function completedCount(
  tasks: Task[],
  attempts: Attempt[],
  submissions: Submission[],
) {
  const done = completedTaskIds(attempts, submissions);
  return tasks.filter((task) => done.has(task.task_id)).length;
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

/**
 * 已经整段标完的模态。训练阶段用它决定什么时候展开这一段的复盘。
 *
 * **按段而不是按条**：一次看十几条对照记不住，看完就忘；一次看两条、
 * 紧接着进入下一个模态，刚标过的东西还在手上。
 */
export function completeModalities(
  tasks: Task[],
  attempts: Attempt[],
  submissions: Submission[],
): Modality[] {
  const done = completedTaskIds(attempts, submissions);
  return buildTaskSections(tasks)
    .filter((section) => section.tasks.every((row) => done.has(row.task.task_id)))
    .map((section) => section.modality);
}

export function orderedTasks(tasks: Task[]) {
  return buildTaskSections(tasks).flatMap((section) =>
    section.tasks.map((row) => row.task),
  );
}
