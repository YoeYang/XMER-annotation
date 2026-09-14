import type { Modality, Sample } from "../types";
import { MODALITY_LABELS } from "../config";

/**
 * 这个样本四个模态的标注曲线，画在罗盘下方原本空着的位置。
 * 只在四个模态**全部提交**后出现——中途看到自己前几条曲线，
 * 标后面的模态时会照着描，而模态之间的差异正是本研究要测的东西。
 *
 * 画法与离线的 scripts/plot_va_curves.py 一致：
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
// 与侧栏同序：三个单模态在前，完整视频最后
const ORDER: Modality[] = ["visual", "audio", "text", "audiovisual"];

export interface CurveSeries {
  modality: Modality;
  samples: Sample[];
}

interface Props {
  series: CurveSeries[];
}

export default function CurvePanel({ series }: Props) {
  const drawable = ORDER.map((m) => series.find((s) => s.modality === m)).filter(
    (s): s is CurveSeries => !!s && s.samples.length >= 2,
  );
  if (!drawable.length) return null;

  const span = Math.max(
    ...drawable.map((s) => s.samples[s.samples.length - 1].media_time),
    0.001,
  );
  const x = (t: number) => PAD_X + (t / span) * (WIDTH - PAD_X * 2);
  const y = (v: number) =>
    PAD_Y + ((1 - Math.max(-1, Math.min(1, v))) / 2) * (HEIGHT - PAD_Y * 2);
  const halfWidth = (arousal: number) =>
    HW_MIN + ((Math.max(-1, Math.min(1, arousal)) + 1) / 2) * (HW_MAX - HW_MIN);

  const total = drawable.reduce((n, s) => n + s.samples.length, 0);
  return (
    <figure className="curve-panel">
      <figcaption>
        <span className="eyebrow">本样本曲线</span>
        <small>中线为效价，色带越宽表示越激动 · 共 {total} 点</small>
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`本样本 ${drawable.length} 个模态的标注曲线`}
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
        {drawable.map(({ modality, samples }) => {
          const line = samples
            .map(
              (s, i) =>
                (i ? "L" : "M") + x(s.media_time) + " " + y(s.valence),
            )
            .join(" ");
          const band =
            samples
              .map(
                (s, i) =>
                  (i ? "L" : "M") +
                  x(s.media_time) +
                  " " +
                  y(s.valence + halfWidth(s.arousal)),
              )
              .join(" ") +
            " " +
            samples
              .slice()
              .reverse()
              .map(
                (s) =>
                  "L" + x(s.media_time) + " " + y(s.valence - halfWidth(s.arousal)),
              )
              .join(" ") +
            " Z";
          return (
            <g key={modality}>
              <path d={band} fill={COLORS[modality]} opacity="0.28" />
              <path
                d={line}
                fill="none"
                stroke={COLORS[modality]}
                strokeWidth="1.5"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </g>
          );
        })}
        <text x="3" y={PAD_Y + 7} className="curve-axis">
          +
        </text>
        <text x="3" y={HEIGHT - PAD_Y - 1} className="curve-axis">
          −
        </text>
      </svg>
      <ul className="curve-legend">
        {drawable.map(({ modality }) => (
          <li key={modality}>
            <i style={{ background: COLORS[modality] }} />
            {MODALITY_LABELS[modality]}
          </li>
        ))}
      </ul>
    </figure>
  );
}
