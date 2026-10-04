import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchLatestVersion, watchForUpdate } from "../src/core/version";

afterEach(() => vi.useRealTimers());

describe("新版本提示（2026-10-05）", () => {
  it("读出服务器上的版本号，并且不走缓存", async () => {
    const fetchFn = vi.fn(async (_u: string, _i?: RequestInit) =>
      new Response(JSON.stringify({ version: "v2" })));
    expect(await fetchLatestVersion("/version.json", fetchFn)).toBe("v2");
    expect(fetchFn).toHaveBeenCalledWith("/version.json", { cache: "no-store" });
  });

  it("取不到、格式不对、服务器报错都返回 null", async () => {
    expect(await fetchLatestVersion("/v", async () => { throw new Error("断网"); })).toBeNull();
    expect(await fetchLatestVersion("/v", async () => new Response("{}"))).toBeNull();
    expect(await fetchLatestVersion("/v", async () => new Response("", { status: 404 }))).toBeNull();
  });

  it("版本相同不提示；不同就提示一次并停止检查", async () => {
    vi.useFakeTimers();
    let latest: string | null = "v1";
    const check = vi.fn(async () => latest);
    const onUpdate = vi.fn();
    watchForUpdate({ current: "v1", check, onUpdate, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(3000);
    expect(onUpdate).not.toHaveBeenCalled();
    latest = "v2";
    await vi.advanceTimersByTimeAsync(1000);
    expect(onUpdate).toHaveBeenCalledTimes(1);
    const calls = check.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(check.mock.calls.length).toBe(calls);
    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it("取不到版本（null）不算有更新", async () => {
    vi.useFakeTimers();
    const onUpdate = vi.fn();
    watchForUpdate({ current: "v1", check: async () => null, onUpdate, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(5000);
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("切回标签页时立刻查一次", async () => {
    const doc = new EventTarget() as EventTarget & { visibilityState: string };
    doc.visibilityState = "visible";
    const onUpdate = vi.fn();
    const stop = watchForUpdate({
      current: "v1", check: async () => "v2", onUpdate, intervalMs: 60_000,
      doc: doc as unknown as Document,
    });
    doc.dispatchEvent(new Event("visibilitychange"));
    await new Promise((r) => setTimeout(r, 0));
    expect(onUpdate).toHaveBeenCalledTimes(1);
    stop();
  });
});
