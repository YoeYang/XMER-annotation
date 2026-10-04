/**
 * 新版本提示（2026-10-05）。
 *
 * 每次构建把同一个版本号写进代码（__APP_VERSION__）和 dist/version.json。页面定期取
 * version.json，发现不一样就提示；标注者点「下一步」时顺势重新载入，不必再在群里
 * 挨个通知刷新。
 */
declare const __APP_VERSION__: string;
export const APP_VERSION: string = __APP_VERSION__;

export const VERSION_CHECK_MS = 5 * 60 * 1000;

/** 服务器上的版本号；取不到就返回 null（断网、旧部署没有这个文件），不当成有更新。 */
export async function fetchLatestVersion(
  url: string,
  fetchFn: (url: string, init?: RequestInit) => Promise<Response> = (u, i) => fetch(u, i),
): Promise<string | null> {
  try {
    const response = await fetchFn(url, { cache: "no-store" });
    if (!response.ok) return null;
    const body = (await response.json()) as { version?: unknown };
    return typeof body.version === "string" ? body.version : null;
  } catch {
    return null;
  }
}

/**
 * 定期检查，发现新版本回调一次后停下。返回停止函数。
 * 切回这个标签页时也查一次：人离开一阵回来，最可能已经有新版本了。
 */
export function watchForUpdate(options: {
  current: string;
  check: () => Promise<string | null>;
  onUpdate: () => void;
  intervalMs?: number;
  doc?: Pick<Document, "addEventListener" | "removeEventListener" | "visibilityState">;
}): () => void {
  const { current, check, onUpdate, intervalMs = VERSION_CHECK_MS, doc } = options;
  let stopped = false;
  const run = async () => {
    if (stopped) return;
    const latest = await check();
    if (!stopped && latest && latest !== current) {
      stop();
      onUpdate();
    }
  };
  const visible = () => {
    if (doc?.visibilityState === "visible") void run();
  };
  const timer = setInterval(() => void run(), intervalMs);
  doc?.addEventListener("visibilitychange", visible);
  function stop() {
    stopped = true;
    clearInterval(timer);
    doc?.removeEventListener("visibilitychange", visible);
  }
  return stop;
}
