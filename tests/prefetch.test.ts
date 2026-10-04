import { describe, expect, it, vi } from "vitest";
import { assetsOf, createPrefetcher, upcoming } from "../src/core/prefetch";
import type { Task } from "../src/types";

const task = (id: string, extra: Partial<Task> = {}): Task => ({
  task_id: id,
  media_id: id,
  display_id: id,
  modality: "face",
  src: `/pool/${id}.mp4`,
  duration: 1,
  target: "",
  demo: false,
  timeline_origin: 0,
  order_index: 0,
  ...extra,
});

const ok = () => new Response(new Uint8Array([1, 2, 3]));

describe("提前下载后面几条的素材（2026-10-04 出口限速）", () => {
  it("取当前之后的两条；最后一条之后没有", () => {
    const list = [task("a"), task("b"), task("c"), task("d")];
    expect(upcoming(list, "a").map((t) => t.task_id)).toEqual(["b", "c"]);
    expect(upcoming(list, "c").map((t) => t.task_id)).toEqual(["d"]);
    expect(upcoming(list, "d")).toEqual([]);
    expect(upcoming(list, "nope")).toEqual([]);
  });

  it("素材和说话人头像都要", () => {
    expect(assetsOf(task("a", { speaker_ref_src: "/pool/a.jpg" }))).toEqual([
      "/pool/a.mp4",
      "/pool/a.jpg",
    ]);
    expect(assetsOf(task("b"))).toEqual(["/pool/b.mp4"]);
  });

  it("一个一个地下，下过的不再下", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const fetchFn = vi.fn(async (_url: string) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight -= 1;
      return ok();
    });
    const p = createPrefetcher(fetchFn);
    await p.prefetch(["/x", "/y", "/z"]);
    await p.prefetch(["/y", "/z"]);
    expect(fetchFn.mock.calls.map((c) => c[0])).toEqual(["/x", "/y", "/z"]);
    expect(maxInFlight).toBe(1);
  });

  it("失败的下次再试，不会让后面的停下", async () => {
    const fetchFn = vi
      .fn()
      .mockRejectedValueOnce(new Error("断网"))
      .mockResolvedValue(ok());
    const p = createPrefetcher(fetchFn);
    await p.prefetch(["/x", "/y"]);
    await p.prefetch(["/x"]);
    expect(fetchFn.mock.calls.map((c) => c[0])).toEqual(["/x", "/y", "/x"]);
  });

  it("服务器返回错误码也算失败、允许重试", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValue(ok());
    const p = createPrefetcher(fetchFn);
    await p.prefetch(["/x"]);
    await p.prefetch(["/x"]);
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("用低优先级、优先走缓存", async () => {
    const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => ok());
    await createPrefetcher(fetchFn).prefetch(["/x"]);
    expect(fetchFn).toHaveBeenCalledWith("/x", { cache: "force-cache", priority: "low" });
  });
});
