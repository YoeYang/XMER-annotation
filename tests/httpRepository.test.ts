import { describe, expect, it, vi } from "vitest";
import { HttpRepository } from "../src/storage/httpRepository";
import type { Attempt, Sample, Task } from "../src/types";
import tasks from "../public/tasks.json";

function attempt(overrides: Partial<Attempt> = {}): Attempt {
  return {
    schema_version: 1,
    attempt_id: "att-1",
    task_id: "DEMO-001",
    annotator_id: "A001",
    media_id: "demo-visual",
    modality: "visual",
    mode: "annotation",
    status: "recording",
    task_snapshot: tasks[0] as Task,
    sample_rate_hz: 10,
    started_at: "2026-09-11T00:00:00.000Z",
    completed_at: null,
    sample_count: 0,
    last_media_time: 0,
    events: [],
    calibration: null,
    ...overrides,
  };
}
const sample = (index: number): Sample => ({
  task_id: "DEMO-001",
  annotator_id: "A001",
  modality: "visual",
  media_id: "demo-visual",
  attempt_id: "att-1",
  sample_index: index,
  media_time: index * 0.1,
  wall_time: "2026-09-11T00:00:00.000Z",
  is_valid: true,
  valence: 0.1,
  arousal: 0.2,
});
const ok = (body: unknown = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

function repo(fetchImpl: typeof fetch, token: string | null = "token-a001") {
  return new HttpRepository({
    baseUrl: "/annotation/api",
    getToken: () => token,
    fetch: fetchImpl,
  });
}

describe("云端存储", () => {
  it("保存草稿时先写轮次元数据，再按批次首个序号写采样块", async () => {
    const fetchImpl = vi.fn(async () => ok());
    await repo(fetchImpl as unknown as typeof fetch).checkpoint(
      attempt({ sample_count: 5 }),
      [sample(3), sample(4)],
    );

    const calls = fetchImpl.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map((c) => c[0])).toEqual([
      "/annotation/api/attempts/att-1",
      "/annotation/api/attempts/att-1/chunks/3",
    ]);
    expect(calls[0][1].method).toBe("PUT");
    expect(JSON.parse(calls[1][1].body as string).samples).toHaveLength(2);
  });

  it("同一批采样重传算出同一个块序号，服务器据此去重", async () => {
    const fetchImpl = vi.fn(async () => ok());
    const repository = repo(fetchImpl as unknown as typeof fetch);
    const batch = [sample(7), sample(8)];
    await repository.checkpoint(attempt(), batch);
    await repository.checkpoint(attempt(), batch);

    const urls = (fetchImpl.mock.calls as unknown as [string][]).map((c) => c[0]);
    expect(urls.filter((u) => u.includes("/chunks/"))).toEqual([
      "/annotation/api/attempts/att-1/chunks/7",
      "/annotation/api/attempts/att-1/chunks/7",
    ]);
  });

  it("没有新采样时只更新轮次元数据，不发空块", async () => {
    const fetchImpl = vi.fn(async () => ok());
    await repo(fetchImpl as unknown as typeof fetch).checkpoint(attempt(), []);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("每个请求都带上令牌", async () => {
    const fetchImpl = vi.fn(async () => ok([]));
    await repo(fetchImpl as unknown as typeof fetch).listAttempts("A001");
    const init = (fetchImpl.mock.calls as unknown as [string, RequestInit][])[0][1];
    expect((init.headers as Record<string, string>).authorization).toBe(
      "Bearer token-a001",
    );
  });

  it("缺少令牌时明确提示，而不是发出匿名请求", async () => {
    const fetchImpl = vi.fn(async () => ok());
    await expect(
      repo(fetchImpl as unknown as typeof fetch, null).listAttempts("A001"),
    ).rejects.toThrow(/令牌/);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("把服务器给出的原因透传给界面", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "该样本未分配给你。" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
    );
    await expect(
      repo(fetchImpl as unknown as typeof fetch).checkpoint(attempt(), []),
    ).rejects.toThrow("该样本未分配给你。");
  });

  it("提交时复用调用方给定的编号，使重试不会变成新版本", async () => {
    const fetchImpl = vi.fn(async () => ok({ submission_id: "sub-1" }));
    await repo(fetchImpl as unknown as typeof fetch).submitWith("att-1", "sub-1");

    const [url, init] = (
      fetchImpl.mock.calls as unknown as [string, RequestInit][]
    )[0];
    expect(url).toBe("/annotation/api/attempts/att-1/submit");
    expect(JSON.parse(init.body as string)).toEqual({ submission_id: "sub-1" });
  });
});
