import { describe, expect, it } from "vitest";
import { completedCount, completedTaskIds, taskComplete } from "../src/core/taskFlow";
import type { Attempt, Submission, Task } from "../src/types";

/** 可复现的伪随机数 */
function rng(seed: number) {
  return () => ((seed = (seed * 1664525 + 1013904223) % 2 ** 32) / 2 ** 32);
}

function world(nTasks: number, nAttempts: number, seed: number) {
  const r = rng(seed);
  const tasks = Array.from({ length: nTasks }, (_, i) => ({ task_id: `T${i}` }) as Task);
  const attempts: Attempt[] = [];
  const submissions: Submission[] = [];
  for (let i = 0; i < nAttempts; i++) {
    const task = tasks[Math.floor(r() * nTasks)].task_id;
    // 时间故意制造并列，检验「并列取后出现的那轮」与原实现一致
    const started = `2026-10-0${1 + Math.floor(r() * 3)}T00:00:0${Math.floor(r() * 3)}Z`;
    const attempt = {
      attempt_id: `A${i}`, task_id: task, dimension: r() < 0.5 ? "valence" : "arousal",
      started_at: started,
    } as Attempt;
    attempts.push(attempt);
    if (r() < 0.7)
      submissions.push({ submission_id: `S${i}`, attempt_id: attempt.attempt_id, task_id: task } as Submission);
  }
  return { tasks, attempts, submissions };
}

describe("完成判定一次遍历（2026-10-05 卡顿修复）", () => {
  it("和逐条判定的结果完全一致", () => {
    for (let seed = 1; seed <= 30; seed++) {
      const { tasks, attempts, submissions } = world(60, 300, seed);
      const fast = completedTaskIds(attempts, submissions);
      for (const task of tasks)
        expect(fast.has(task.task_id), `seed ${seed} ${task.task_id}`).toBe(
          taskComplete(attempts, submissions, task.task_id),
        );
    }
  });

  it("只交了一维、或最新一轮没交，都不算完成", () => {
    const attempts = [
      { attempt_id: "v1", task_id: "T", dimension: "valence", started_at: "2026-10-01T00:00:00Z" },
      { attempt_id: "a1", task_id: "T", dimension: "arousal", started_at: "2026-10-01T00:00:01Z" },
      { attempt_id: "a2", task_id: "T", dimension: "arousal", started_at: "2026-10-01T00:00:02Z" },
    ] as Attempt[];
    const subs = (ids: string[]) => ids.map((id) => ({ attempt_id: id }) as Submission);
    expect(completedTaskIds(attempts, subs(["v1"])).has("T")).toBe(false);
    expect(completedTaskIds(attempts, subs(["v1", "a1"])).has("T")).toBe(false); // 重标的 a2 没交
    expect(completedTaskIds(attempts, subs(["v1", "a2"])).has("T")).toBe(true);
  });

  it("大账号（3420 条任务、7000 轮、5000 提交）几十毫秒内算完", () => {
    const { tasks, attempts, submissions } = world(3420, 7000, 7);
    const start = performance.now();
    completedCount(tasks, attempts, submissions);
    expect(performance.now() - start).toBeLessThan(100);
  });
});
