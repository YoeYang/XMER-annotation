import type { Task } from "../types";

/**
 * 标当前这条时，后台把后面几条的素材先下好（2026-10-04）。
 *
 * 服务器出口限速约 5 Mbps：平均用量不到 1 Mbps，但大家都是「点下一步才开始下」，
 * 几个人赶在同一刻就互相拖慢，一条 1 MB 的视频要等好几秒。一条子任务要标约 25 秒，
 * 下载只要一两秒，提前下好就几乎不用等。素材带长期缓存头（Caddy），下好的文件
 * 播放器直接从浏览器缓存里取。总流量不变，只是错开了时间。
 */

/** 当前任务之后的 `count` 条（队列里的顺序就是「下一步」的顺序）。 */
export function upcoming(tasks: Task[], selectedId: string, count = 2): Task[] {
  const index = tasks.findIndex((task) => task.task_id === selectedId);
  if (index < 0) return [];
  return tasks.slice(index + 1, index + 1 + count);
}

/** 一条任务要用到的文件：素材（视频 / 音频 / 文本稿）和说话人头像。 */
export function assetsOf(task: Task): string[] {
  return [task.src, task.speaker_ref_src].filter(
    (path): path is string => Boolean(path),
  );
}

/**
 * 一个一个地下：同时下几个会和正在播放的那条抢带宽，反而更卡。
 * 下过的不再下；失败的从记录里删掉，下次换任务时会再试。
 */
export function createPrefetcher(
  fetchFn: (url: string, init?: RequestInit) => Promise<Response> = (url, init) =>
    fetch(url, init),
) {
  const seen = new Set<string>();
  const queue: string[] = [];
  let running = false;

  async function drain() {
    if (running) return;
    running = true;
    while (queue.length) {
      const url = queue.shift()!;
      try {
        const response = await fetchFn(url, {
          cache: "force-cache",
          priority: "low",
        } as RequestInit);
        if (!response.ok) throw new Error(String(response.status));
        // 读完响应体才算真正进了缓存
        await response.arrayBuffer();
      } catch {
        seen.delete(url);
      }
    }
    running = false;
  }

  return {
    prefetch(urls: string[]) {
      for (const url of urls) {
        if (seen.has(url)) continue;
        seen.add(url);
        queue.push(url);
      }
      return drain();
    },
  };
}
