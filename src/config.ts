import type { Modality, Phase } from "./types";
export const SAMPLE_RATE_HZ = 10;
export const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5];
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
