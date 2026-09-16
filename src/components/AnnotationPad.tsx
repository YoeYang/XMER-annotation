import { useRef } from "react";
import { Frown, Smile, Moon, Zap, BookOpen } from "lucide-react";
import { normalizeValue } from "../core/sampler";
import type { Dimension, FlowPage, SessionView } from "../types";

interface Props {
  page: FlowPage;
  view: SessionView;
  canAnnotate: boolean;
  onPress: (value: number) => void;
  onMove: (value: number) => void;
  onRelease: () => void;
  onGuide: () => void;
}

const labels: Record<Dimension, { title: string; low: string; high: string }> =
  {
    valence: { title: "效价 Valence", low: "负向 −1", high: "正向 +1" },
    arousal: { title: "唤醒 Arousal", low: "冷静 −1", high: "激动 +1" },
  };

function HoldMouse({ pressed = true }: { pressed?: boolean }) {
  return (
    <svg className="hold-mouse" viewBox="0 0 32 44" aria-hidden="true">
      {pressed && (
        <path d="M16 3C8 3 4 8 4 16v4h12Z" className="mouse-left-button" />
      )}
      <rect
        x="4"
        y="3"
        width="24"
        height="38"
        rx="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
      />
      <path
        d="M16 3v17M4 20h24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  );
}

export default function AnnotationPad({
  page,
  view,
  canAnnotate,
  onPress,
  onMove,
  onRelease,
  onGuide,
}: Props) {
  const pointer = useRef<number | null>(null);
  const activeDimension = page === "familiarization" ? null : page;
  const valueAt = (clientX: number, element: HTMLElement) => {
    const box = element.getBoundingClientRect();
    return normalizeValue(clientX - box.left, box.width);
  };

  const heading = (
    <div className="dimension-heading">
      <h2 id="dimension-title">
        {activeDimension ? labels[activeDimension].title : "先熟悉"}
      </h2>
      <button className="annotation-guide" onClick={onGuide}>
        <BookOpen size={18} />
        标注指南
      </button>
    </div>
  );
  if (!activeDimension) {
    return (
      <section
        className="v3-step-panel familiarization-copy"
        aria-label="熟悉材料"
      >
        {heading}
        <p>看懂即可继续</p>
      </section>
    );
  }

  const sampling = view.phase === "recording";
  const dimensions: Dimension[] = ["valence", "arousal"];
  return (
    <section className="v3-step-panel" aria-labelledby="dimension-title">
      {heading}
      <div
        className={"sampling-strip " + (sampling ? "sampling" : "paused")}
        role="status"
      >
        <span className="status-dot" />
        {view.phase === "completed"
          ? "已完成"
          : sampling
            ? "采样中…"
            : view.phase === "hold-delay"
              ? "准备中…"
              : "暂停采样…"}
      </div>
      <div className="dimension-bars">
        {dimensions.map((dimension) => {
          const active = dimension === activeDimension;
          return (
            <div
              className={"dimension-row " + (active ? "active" : "inactive")}
              data-dimension={dimension}
              key={dimension}
            >
              <div className="dimension-label">{labels[dimension].title}</div>
              <div className="bar-semantics">
                <span>
                  {dimension === "valence" ? (
                    <Frown aria-hidden="true" />
                  ) : (
                    <Moon aria-hidden="true" />
                  )}
                  {labels[dimension].low}
                </span>
                <span>
                  {labels[dimension].high}
                  {dimension === "valence" ? (
                    <Smile aria-hidden="true" />
                  ) : (
                    <Zap aria-hidden="true" />
                  )}
                </span>
              </div>
              <div
                className="dimension-bar"
                aria-label={
                  active ? labels[dimension].title + "标注条" : undefined
                }
                aria-describedby={active ? "hold-hint" : undefined}
                aria-disabled={!active || !canAnnotate}
                onContextMenu={(event) => event.preventDefault()}
                onPointerDown={(event) => {
                  if (
                    event.button !== 0 ||
                    !active ||
                    !canAnnotate ||
                    pointer.current !== null
                  )
                    return;
                  event.preventDefault();
                  pointer.current = event.pointerId;
                  event.currentTarget.setPointerCapture(event.pointerId);
                  onPress(valueAt(event.clientX, event.currentTarget));
                }}
                onPointerMove={(event) => {
                  if (
                    !active ||
                    !canAnnotate ||
                    pointer.current !== event.pointerId
                  )
                    return;
                  onMove(valueAt(event.clientX, event.currentTarget));
                }}
                onPointerUp={(event) => {
                  if (pointer.current !== event.pointerId) return;
                  pointer.current = null;
                  if (event.currentTarget.hasPointerCapture(event.pointerId))
                    event.currentTarget.releasePointerCapture(event.pointerId);
                  onRelease();
                }}
                onLostPointerCapture={(event) => {
                  if (pointer.current !== event.pointerId) return;
                  pointer.current = null;
                  onRelease();
                }}
                onPointerCancel={(event) => {
                  if (pointer.current !== event.pointerId) return;
                  pointer.current = null;
                  onRelease();
                }}
              >
                {active && (
                  <span
                    className={
                      "bar-cursor " +
                      (view.value === null ? "initial-cursor" : "")
                    }
                    style={{ left: (((view.value ?? 0) + 1) / 2) * 100 + "%" }}
                    aria-hidden="true"
                  >
                    {view.value === null && <HoldMouse />}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="bar-feedback">
        <div id="hold-hint" className="mouse-hints">
          <span className="hold-hint">
            <HoldMouse />
            任意位置按住
          </span>
          <span className="hold-hint">
            <HoldMouse pressed={false} />
            松开暂停
          </span>
        </div>
        <output className="active-value" data-testid="dimension-value">
          {view.value === null ? "" : view.value.toFixed(2)}
        </output>
      </div>
    </section>
  );
}
