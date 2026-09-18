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
// 界面文案统一在 i18n.ts；这里只留与语言无关的常量。
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
