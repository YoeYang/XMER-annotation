import type { ReactNode } from "react";
import { MousePointer2 } from "lucide-react";
import type { Point, SessionView } from "../types";
import { normalizePoint } from "../core/sampler";
import CurvePanel from "./CurvePanel";
interface Props {
  view: SessionView;
  onStart: (point: Point) => void;
  onMove: (point: Point) => void;
  /** 保存 / 重新标注 / 导出。放在标题栏右侧，一次标注不必滚动到页面底部。 */
  actions: ReactNode;
}
export default function AnnotationPad({
  view,
  onStart,
  onMove,
  actions,
}: Props) {
  const completedAnnotation =
    view.phase === "completed" && view.attempt?.mode === "annotation";
  const suspendedAnnotation =
    ["paused", "buffering"].includes(view.phase) &&
    view.attempt?.mode === "annotation";
  const disabled =
    ["loading", "starting", "error"].includes(view.phase) ||
    completedAnnotation ||
    suspendedAnnotation;
  const canStart = view.phase === "ready" || view.attempt?.mode === "preview";
  const position = view.point ?? { valence: 0, arousal: 0 };
  return (
    <section
      className="panel annotation-panel"
      aria-labelledby="annotation-title"
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">02 / ANNOTATE</span>
          <h2 id="annotation-title">感知此刻的情绪</h2>
        </div>
        {actions}
      </div>
      <p className="panel-description">
        根据目标人物当前的情感状态，连续移动光标。
      </p>
      <div className="pad-frame">
        <div className="axis-arousal top">
          激动 <small>high arousal</small>
        </div>
        <div className="pad-row">
          <div className="axis-valence left">
            负面
            <small>negative</small>
          </div>
          <div
            className="pad"
            role="button"
          tabIndex={disabled ? -1 : 0}
          aria-label="二维情绪标注区域"
          aria-disabled={disabled}
          onPointerDown={(event) => {
            if (disabled || !canStart) return;
            const box = event.currentTarget.getBoundingClientRect();
            onStart(
              normalizePoint(
                event.clientX - box.left,
                event.clientY - box.top,
                box.width,
                box.height,
              ),
            );
          }}
          onPointerMove={(event) => {
            if (disabled || view.attempt?.mode !== "annotation") return;
            const box = event.currentTarget.getBoundingClientRect();
            onMove(
              normalizePoint(
                event.clientX - box.left,
                event.clientY - box.top,
                box.width,
                box.height,
              ),
            );
          }}
          onKeyDown={(event) => {
            if (disabled) return;
            if ((event.key === "Enter" || event.key === " ") && canStart) {
              event.preventDefault();
              onStart(position);
            }
            const delta: Record<string, Point> = {
              ArrowLeft: { valence: -0.05, arousal: 0 },
              ArrowRight: { valence: 0.05, arousal: 0 },
              ArrowUp: { valence: 0, arousal: 0.05 },
              ArrowDown: { valence: 0, arousal: -0.05 },
            };
            if (delta[event.key]) {
              event.preventDefault();
              onMove({
                valence: Math.max(
                  -1,
                  Math.min(1, position.valence + delta[event.key].valence),
                ),
                arousal: Math.max(
                  -1,
                  Math.min(1, position.arousal + delta[event.key].arousal),
                ),
              });
            }
          }}
          >
            <span className="cross horizontal" />
            <span className="cross vertical" />
            <span
              className={"cursor-point " + (view.point ? "selected" : "")}
              style={{
                left: ((position.valence + 1) / 2) * 100 + "%",
                top: ((1 - position.arousal) / 2) * 100 + "%",
              }}
            />
            {canStart && !disabled && (
              <span className="start-hint">
                <MousePointer2 size={16} />
                点击任意位置开始
              </span>
            )}
          </div>
          <div className="axis-valence right">
            正面
            <small>positive</small>
          </div>
        </div>
        <div className="axis-arousal low">
          平静 <small>low arousal</small>
        </div>
      </div>
      <div className="coordinate-values">
        <div>
          <span>
            <i className="dot teal" />
            Valence <small>效价</small>
          </span>
          <strong data-testid="valence">{position.valence.toFixed(2)}</strong>
        </div>
        <div>
          <span>
            <i className="dot amber" />
            Arousal <small>唤醒度</small>
          </span>
          <strong data-testid="arousal">{position.arousal.toFixed(2)}</strong>
        </div>
      </div>
      <p className="pad-note">
        <MousePointer2 size={14} />
        无需按住鼠标；离开区域后保持最后位置。
      </p>
      {completedAnnotation && view.attempt && (
        <CurvePanel
          curve={view.curve}
          modality={view.attempt.modality}
          duration={view.duration}
        />
      )}
    </section>
  );
}
