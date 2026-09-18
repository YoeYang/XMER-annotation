import { useEffect, useRef } from "react";
import type { Dimension, TracePoint } from "../types";
import { useLang } from "../LangContext";

/**
 * 标注轨迹的实时预览：横轴媒体时间，纵轴 −1…+1。
 *
 * 标注者按住拖动时只能感觉到"手往哪边挪"，看不到自己画出了什么形状。
 * 一条随采样长出来的线让人对自己的判断有个整体印象——尤其是发现
 * "我怎么一路平着没动"或者"刚才那下抖太大了"。
 *
 * 刻意画得简单：它是**旁证**不是标注对象，抢了注意力反而干扰判断。
 * 没有坐标轴数字、没有网格，只有一条零线和一条轨迹。
 */
const COLOR: Record<Dimension, string> = {
  valence: "#c77d2e",
  arousal: "#8e4a86",
};

export default function TraceChart({
  trace,
  duration,
  time,
  dimension,
}: {
  trace: TracePoint[];
  duration: number;
  time: number;
  dimension: Dimension | null;
}) {
  const { t } = useLang();
  const canvas = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const node = canvas.current;
    if (!node || !dimension) return;
    const scale = window.devicePixelRatio || 1;
    const width = node.clientWidth;
    const height = node.clientHeight;
    if (!width || !height) return;
    // 按设备像素比放大画布，否则高分屏上线条发糊
    node.width = Math.round(width * scale);
    node.height = Math.round(height * scale);
    const ctx = node.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const span = Math.max(duration, 0.001);
    const x = (t: number) => (t / span) * width;
    const y = (v: number) => height / 2 - v * (height / 2 - 3);

    ctx.strokeStyle = "#d8d4cc";      // 零线
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
    ctx.stroke();

    if (time > 0) {                    // 播放位置
      ctx.strokeStyle = "#bdb8ae";
      ctx.beginPath();
      ctx.moveTo(x(time), 0);
      ctx.lineTo(x(time), height);
      ctx.stroke();
    }

    if (trace.length) {
      ctx.strokeStyle = COLOR[dimension];
      ctx.lineWidth = 1.8;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      trace.forEach((point, index) => {
        const px = x(point.t);
        const py = y(point.v);
        index === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      });
      ctx.stroke();

      const last = trace[trace.length - 1];
      ctx.fillStyle = COLOR[dimension];
      ctx.beginPath();
      ctx.arc(x(last.t), y(last.v), 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }, [trace, trace.length, duration, time, dimension]);

  if (!dimension) return null;
  return (
    <div className="trace-chart">
      <canvas ref={canvas} aria-hidden="true" />
      <span className="trace-hint">
        {trace.length ? t("trace.yours") : t("trace.empty")}
      </span>
    </div>
  );
}
