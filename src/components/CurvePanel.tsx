import type { Modality, Sample } from "../types";
import { MODALITY_LABELS } from "../config";

/**
 * 本轮标注结果的回看图，画在罗盘下方原本空着的位置。
 * 只在标注结束后出现——标注过程中盯着自己的曲线会跟着曲线走，而不是跟着材料走。
 *
 * 画法与离线的 scripts/plot_va_curves.py 保持一致：
 * 中线是效价，围绕中线的色带宽度表示唤醒度，带越宽越激动。
 */
const WIDTH = 420,
  HEIGHT = 132,
  PAD_X = 22,
  PAD_Y = 10;
// 带宽（效价单位）由唤醒度 -1..1 映射而来，与离线脚本同一组常数
const HW_MIN = 0.015,
  HW_MAX = 0.22;
const COLORS: Record<Modality, string> = {
  audiovisual: "#2f6f6a",
  visual: "#c65d3b",
  audio: "#3a6ea5",
  text: "#b08a2e",
};

interface Props {
  curve: Sample[];
  modality: Modality;
  duration: number;
}

export default function CurvePanel({ curve, modality, duration }: Props) {
  if (curve.length < 2) return null;
  const span = Math.max(duration, curve[curve.length - 1].media_time, 0.001);
  const x = (t: number) => PAD_X + (t / span) * (WIDTH - PAD_X * 2);
  const y = (v: number) =>
    PAD_Y + ((1 - Math.max(-1, Math.min(1, v))) / 2) * (HEIGHT - PAD_Y * 2);
  const halfWidth = (arousal: number) =>
    HW_MIN + (Math.max(-1, Math.min(1, arousal)) + 1) / 2 * (HW_MAX - HW_MIN);

  const line = curve
    .map((s, i) => (i ? "L" : "M") + x(s.media_time) + " " + y(s.valence))
    .join(" ");
  const band =
    curve
      .map(
        (s, i) =>
          (i ? "L" : "M") +
          x(s.media_time) +
          " " +
          y(s.valence + halfWidth(s.arousal)),
      )
      .join(" ") +
    " " +
    curve
      .slice()
      .reverse()
      .map((s) => "L" + x(s.media_time) + " " + y(s.valence - halfWidth(s.arousal)))
      .join(" ") +
    " Z";

  const color = COLORS[modality];
  return (
    <figure className="curve-panel">
      <figcaption>
        <span className="eyebrow">本轮曲线</span>
        <small>
          中线为效价，色带越宽表示越激动 · {MODALITY_LABELS[modality]} ·{" "}
          {curve.length} 点
        </small>
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`本轮标注曲线，共 ${curve.length} 个采样点`}
        preserveAspectRatio="none"
      >
        <line
          x1={PAD_X}
          x2={WIDTH - PAD_X}
          y1={y(0)}
          y2={y(0)}
          stroke="#c9d2c6"
          strokeWidth="1"
          strokeDasharray="4 4"
        />
        <path d={band} fill={color} opacity="0.35" />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth="1.6"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <text x="3" y={PAD_Y + 7} className="curve-axis">
          +
        </text>
        <text x="3" y={HEIGHT - PAD_Y - 1} className="curve-axis">
          −
        </text>
      </svg>
    </figure>
  );
}
