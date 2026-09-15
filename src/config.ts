import type { Modality, Phase } from "./types";
export const SAMPLE_RATE_HZ = 10;
// 0.1 与 0.3 是标注者要求的：素材里情绪变得太快，常速跟不上手。
// 采样按媒体时间定频，放慢不会改变曲线的时间分辨率，只是给人更多反应余地。
export const PLAYBACK_RATES = [0.1, 0.3, 0.5, 0.75, 1, 1.25, 1.5];
const RATE_KEY = "xmer.playback_rate";
/**
 * 倍速跨任务、跨刷新保持。
 * 微表情细微的样本要放慢才标得动，而一个人一次要标几十个任务，
 * 每换一个就重选一次倍速太折腾。
 * 浏览器可能禁用存储（隐私模式），读写都得能失败。
 */
export function rememberedRate(): number {
  try {
    const value = Number(localStorage.getItem(RATE_KEY));
    return PLAYBACK_RATES.includes(value) ? value : 1;
  } catch {
    return 1;
  }
}
export function rememberRate(rate: number): void {
  try {
    localStorage.setItem(RATE_KEY, String(rate));
  } catch {
    // 存不下就只在本次会话里生效，不该因此中断标注
  }
}
export const MODALITY_LABELS: Record<Modality, string> = {
  visual: "仅视觉",
  audio: "仅音频",
  text: "仅文本",
  audiovisual: "完整视频",
};
export const PHASE_LABELS: Record<Phase, string> = {
  loading: "加载材料中",
  ready: "等待开始",
  starting: "正在开始",
  preview: "正在预览",
  recording: "正在采样",
  paused: "已暂停",
  buffering: "正在缓冲",
  completed: "本轮已完成",
  error: "加载或播放失败",
};
export function resolveAssetPath(path: string): string {
  const base = import.meta.env.BASE_URL;
  return base.endsWith("/")
    ? base + path.replace(/^\//, "")
    : base + "/" + path.replace(/^\//, "");
}
// 子路径部署时 API 也在 base 之下，与静态资源同理
export const API_BASE = resolveAssetPath("/api");
export function formatTime(seconds: number) {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  return (
    String(Math.floor(safe / 60)).padStart(2, "0") +
    ":" +
    String(Math.floor(safe % 60)).padStart(2, "0")
  );
}
export function formatDate(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "—";
}
