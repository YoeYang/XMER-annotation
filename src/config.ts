import type { Modality, Phase } from "./types";
export const SAMPLE_RATE_HZ = 10;
export const HOLD_START_DELAY_MS = 500;
// 采样按媒体时间定频，放慢不会改变曲线的时间分辨率。
export const PLAYBACK_RATES = [0.1, 0.3, 0.5, 0.7, 1] as const;
export const FAMILIARIZATION_RATE = 1;
export const ANNOTATION_RATE = 0.5;
const RATE_KEY = "xmer.annotation_rate";
export function annotationRate(): number {
  try {
    const value = Number(localStorage.getItem(RATE_KEY));
    return PLAYBACK_RATES.some((rate) => rate === value)
      ? value
      : ANNOTATION_RATE;
  } catch {
    return ANNOTATION_RATE;
  }
}
export function rememberAnnotationRate(rate: number) {
  try {
    localStorage.setItem(RATE_KEY, String(rate));
  } catch {
    // 禁用浏览器存储时，当前会话的选择仍由 session 保留。
  }
}
export const MODALITY_LABELS: Record<Modality, string> = {
  audio: "仅音频",
  text: "仅文本",
  face: "面部",
  body: "身体",
  audiovisual: "完整视频",
};
export const PHASE_LABELS: Record<Phase, string> = {
  loading: "加载材料中",
  ready: "等待开始",
  starting: "正在开始",
  familiarizing: "正在熟悉",
  "hold-delay": "准备采样",
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
