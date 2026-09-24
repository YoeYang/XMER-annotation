import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useLang } from "../LangContext";
import type { Key, Lang } from "../i18n";
import { API_BASE, resolveAssetPath } from "../config";
import { getToken } from "../auth";
import type { Dimension, Modality } from "../types";

interface Point {
  t: number;
  v: number;
}
interface Pair {
  dimension: Dimension;
  mine: Point[];
  reference: Point[];
  note_en: string | null;
  note_zh: string | null;
  note_fi: string | null;
}
interface Item {
  task_id: string;
  display_id: string | null;
  modality: Modality;
  src: string;
  duration: number;
  pairs: Pair[];
}

const COLOUR: Record<Dimension, string> = {
  valence: "#246d5d",
  arousal: "#c06a3f",
};

/**
 * 两条曲线画在一张图上：实线是标注者自己的，虚线是参考。
 *
 * 时间轴按**素材时长**归一，不按采样点个数——两条曲线的点数几乎不会相同
 * （按住的时长不同、松手的位置不同），按点数对齐会让两条线在时间上错开，
 * 而这张图的全部意义就是看「同一时刻两个人标得差多少」。
 */
function Chart({ pair, duration }: { pair: Pair; duration: number }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const context = node.getContext("2d");
    if (!context) return;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    node.width = node.clientWidth * ratio;
    node.height = node.clientHeight * ratio;
    const pad = 8 * ratio;
    const x = (t: number) =>
      pad + (t / Math.max(duration, 0.001)) * (node.width - 2 * pad);
    const y = (v: number) => node.height / 2 - v * (node.height / 2 - pad);

    context.clearRect(0, 0, node.width, node.height);
    context.strokeStyle = "#e3e9ef";
    context.lineWidth = ratio;
    for (const value of [1, 0, -1]) {
      context.beginPath();
      context.moveTo(pad, y(value));
      context.lineTo(node.width - pad, y(value));
      context.stroke();
    }
    const line = (points: Point[], dashed: boolean) => {
      if (!points.length) return;
      context.setLineDash(dashed ? [5 * ratio, 4 * ratio] : []);
      context.strokeStyle = COLOUR[pair.dimension];
      context.globalAlpha = dashed ? 0.55 : 1;
      context.lineWidth = (dashed ? 1.6 : 2) * ratio;
      context.beginPath();
      points.forEach((point, index) => {
        const px = x(point.t);
        const py = y(point.v);
        index ? context.lineTo(px, py) : context.moveTo(px, py);
      });
      context.stroke();
      context.globalAlpha = 1;
      context.setLineDash([]);
    };
    line(pair.reference, true);
    line(pair.mine, false);
  }, [pair, duration]);
  return <canvas ref={canvas} className="debrief-chart" />;
}

interface Props {
  modality: Modality;
  onClose: () => void;
}

export default function Debrief({ modality, onClose }: Props) {
  const { t, lang } = useLang();
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(
          API_BASE + "/training/debrief/" + modality,
          {
            signal: controller.signal,
            headers: { authorization: "Bearer " + (getToken() ?? "") },
          },
        );
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail ?? t("debrief.failed"));
        }
        const data = await response.json();
        if (!controller.signal.aborted) setItems(data.items);
      } catch (problem) {
        if (!controller.signal.aborted)
          setError(problem instanceof Error ? problem.message : t("debrief.failed"));
      }
    })();
    return () => controller.abort();
  }, [modality]);

  const note = (pair: Pair) =>
    ({ en: pair.note_en, zh: pair.note_zh, fi: pair.note_fi } as Record<
      Lang,
      string | null
    >)[lang] ?? pair.note_en;

  return (
    <div className="debrief-backdrop">
      <article className="debrief">
        <header>
          <div>
            <h1>{t("debrief.title")}</h1>
            <p>
              {t(("modality." + modality) as Key)} · {t("debrief.lead")}
            </p>
          </div>
          <button className="ghost" onClick={onClose} aria-label={t("debrief.close")}>
            <X size={15} />
            {t("debrief.close")}
          </button>
        </header>

        <div className="debrief-legend">
          <span className="mine">{t("debrief.mine")}</span>
          <span className="ref">{t("debrief.reference")}</span>
        </div>

        {error && <p className="debrief-error">{error}</p>}
        {!items && !error && <p className="debrief-loading">{t("debrief.loading")}</p>}

        {items?.map((item) => (
          <section className="debrief-item" key={item.task_id}>
            <h2>{item.display_id ?? item.task_id}</h2>
            {item.modality === "audio" ? (
              <audio controls src={resolveAssetPath(item.src)} />
            ) : item.modality === "text" ? null : (
              <video controls playsInline src={resolveAssetPath(item.src)} />
            )}
            {item.pairs.map((pair) => (
              <div className="debrief-pair" key={pair.dimension}>
                <h3 style={{ color: COLOUR[pair.dimension] }}>
                  {t(("dim." + pair.dimension) as Key)}
                </h3>
                <Chart pair={pair} duration={item.duration} />
                {note(pair) && <p className="debrief-note">{note(pair)}</p>}
              </div>
            ))}
          </section>
        ))}

        <div className="debrief-actions">
          <button className="primary" onClick={onClose}>
            {t("debrief.continue")}
          </button>
        </div>
      </article>
    </div>
  );
}
