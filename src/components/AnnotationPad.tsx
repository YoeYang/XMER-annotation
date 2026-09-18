import { useRef } from "react";
import { Annoyed, BookOpen, Frown, Smile, Zap } from "lucide-react";
import { normalizeValue } from "../core/sampler";
import { useLang } from "../LangContext";
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
  const { t } = useLang();
  const pointer = useRef<number | null>(null);
  const scale = (dimension: Dimension) => ({
    title: t(dimension === "valence" ? "dim.valence" : "dim.arousal"),
    top: t(dimension === "valence" ? "valence.high" : "arousal.high"),
    middle: t(dimension === "valence" ? "valence.mid" : "arousal.mid"),
    bottom: t(dimension === "valence" ? "valence.low" : "arousal.low"),
  });
  const activeDimension = page === "familiarization" ? null : page;
  // 纵向取值：**上为 +1、下为 −1**，与视频下方那条曲线同向——
  // 横着拖而曲线上下走，人得在脑子里转一次向，判断就慢一拍。
  // normalizeValue 给的是「起点为 −1」，屏幕 y 轴向下，所以取反。
  const valueAt = (clientY: number, element: HTMLElement) => {
    const box = element.getBoundingClientRect();
    return -normalizeValue(clientY - box.top, box.height);
  };

  const heading = (
    <div className="dimension-heading">
      <h2 id="dimension-title">
        {activeDimension ? scale(activeDimension).title : t("step.familiarize")}
      </h2>
      <button className="annotation-guide" onClick={onGuide}>
        <BookOpen size={18} />
        {t("guide.title")}
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
        <p>{t("step.ready")}</p>
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
          ? t("state.done")
          : sampling
            ? t("state.recording")
            : view.phase === "hold-delay"
              ? t("state.starting")
              : t("state.paused")}
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
              <div className="dimension-label">{scale(dimension).title}</div>
              <div className="bar-track">
              <div className="bar-semantics">
                <span className="end-high">
                  {dimension === "valence" ? (
                    <Smile aria-hidden="true" />
                  ) : (
                    <Zap aria-hidden="true" />
                  )}
                  {scale(dimension).top} +1
                </span>
                <span className="end-mid">{scale(dimension).middle} 0</span>
                <span className="end-low">
                  {dimension === "valence" ? (
                    <Frown aria-hidden="true" />
                  ) : (
                    <Annoyed aria-hidden="true" />
                  )}
                  {scale(dimension).bottom} −1
                </span>
              </div>
              <div
                className="dimension-bar"
                aria-label={
                  active ? scale(dimension).title : undefined
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
                  onPress(valueAt(event.clientY, event.currentTarget));
                }}
                onPointerMove={(event) => {
                  if (
                    !active ||
                    !canAnnotate ||
                    pointer.current !== event.pointerId
                  )
                    return;
                  onMove(valueAt(event.clientY, event.currentTarget));
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
                    style={{ top: ((1 - (view.value ?? 0)) / 2) * 100 + "%" }}
                    aria-hidden="true"
                  >
                    {view.value === null && <HoldMouse />}
                  </span>
                )}
              </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="bar-feedback">
        <div id="hold-hint" className="mouse-hints">
          <span className="hold-hint">
            <HoldMouse />
            {t("hold.hold")}
          </span>
          <span className="hold-hint">
            <HoldMouse pressed={false} />
            {t("hold.release")}
          </span>
        </div>
        <output className="active-value" data-testid="dimension-value">
          {view.value === null ? "" : view.value.toFixed(2)}
        </output>
      </div>
    </section>
  );
}
