import { useEffect, useRef } from "react";
import { PartyPopper } from "lucide-react";
import { useLang } from "../LangContext";

interface Props {
  completed: number;
  onBack: () => void;
}

/** 一粒纸屑。位置用像素，角度用弧度，`spin` 是每帧转过的角度。 */
interface Fleck {
  x: number;
  y: number;
  vx: number;
  vy: number;
  angle: number;
  spin: number;
  size: number;
  colour: string;
}

const COLOURS = ["#246d5d", "#e6b422", "#d8683f", "#5f9ea0", "#b4436c"];

function reducedMotion() {
  try {
    return matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * 全部标完之后的收尾页。
 *
 * **为什么非要有这一页**：从前标完最后一条，界面和标到一半时长得一模一样，
 * 标注者没有任何「到头了」的信号。试标时就这样丢过一条——最后一遍标完没提交
 * 就离开了，数据留在库里却算不上完成。收尾页把「结束」变成看得见的事。
 */
export default function AllDone({ completed, onBack }: Props) {
  const { t } = useLang();
  const canvas = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const node = canvas.current;
    if (!node || reducedMotion()) return;
    const context = node.getContext("2d");
    if (!context) return;

    const ratio = Math.min(devicePixelRatio || 1, 2);
    const resize = () => {
      node.width = node.clientWidth * ratio;
      node.height = node.clientHeight * ratio;
    };
    resize();
    addEventListener("resize", resize);

    const width = () => node.width;
    const flecks: Fleck[] = Array.from({ length: 140 }, () => ({
      x: Math.random() * width(),
      y: -Math.random() * node.height,
      vx: (Math.random() - 0.5) * 1.6 * ratio,
      vy: (1.2 + Math.random() * 2.2) * ratio,
      angle: Math.random() * Math.PI * 2,
      spin: (Math.random() - 0.5) * 0.24,
      size: (4 + Math.random() * 5) * ratio,
      colour: COLOURS[Math.floor(Math.random() * COLOURS.length)],
    }));

    let frame = 0;
    let alive = true;
    const draw = () => {
      if (!alive) return;
      frame += 1;
      context.clearRect(0, 0, node.width, node.height);
      // 落到底就不再补充：撒花是个「一次」的庆祝，循环不停会变成噪音
      let visible = 0;
      for (const fleck of flecks) {
        if (fleck.y > node.height + 20) continue;
        visible += 1;
        fleck.x += fleck.vx;
        fleck.y += fleck.vy;
        fleck.vy += 0.012 * ratio;
        fleck.angle += fleck.spin;
        context.save();
        context.translate(fleck.x, fleck.y);
        context.rotate(fleck.angle);
        context.fillStyle = fleck.colour;
        context.fillRect(-fleck.size / 2, -fleck.size / 4, fleck.size, fleck.size / 2);
        context.restore();
      }
      if (visible === 0 || frame > 900) return;
      requestAnimationFrame(draw);
    };
    requestAnimationFrame(draw);

    return () => {
      alive = false;
      removeEventListener("resize", resize);
    };
  }, []);

  return (
    <div className="all-done" role="status">
      <canvas ref={canvas} className="all-done-confetti" aria-hidden="true" />
      <div className="all-done-card">
        <PartyPopper size={40} strokeWidth={1.4} />
        <h2>{t("done.title")}</h2>
        <p className="all-done-count">{completed}</p>
        <p className="all-done-unit">{t("done.count")}</p>
        <p className="all-done-body">{t("done.body")}</p>
        <button className="ghost" onClick={onBack}>
          {t("done.back")}
        </button>
      </div>
    </div>
  );
}
