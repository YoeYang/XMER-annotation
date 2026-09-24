import {
  Clapperboard,
  CornerDownLeft,
  Headphones,
  MousePointer,
  MousePointerClick,
  PersonStanding,
  Type,
  User,
} from "lucide-react";
import { useLang } from "../LangContext";
import type { Key } from "../i18n";
import { MODALITY_ORDER } from "../core/taskFlow";
import type { Modality } from "../types";

const ICON: Record<Modality, typeof User> = {
  face: User,
  body: PersonStanding,
  audio: Headphones,
  text: Type,
  audiovisual: Clapperboard,
};

interface Props {
  onStart: () => void;
  startLabel?: Key;
}

/**
 * 五个模态的完整标注指南，训练账号进来先看这一页。
 *
 * **和标注时那个弹窗的分工**：弹窗只讲当前这一个模态，是开标前的最后提醒；
 * 这一页把五个模态摆在一起，让人看见它们的区别——「同一段素材，只看脸
 * 和只听声音标出来不一样」这件事，分五次每次只看一个是看不出来的，
 * 而那正是这个数据集要研究的东西。
 */
export default function GuideBook({ onStart, startLabel = "book.start" }: Props) {
  const { t } = useLang();
  return (
    <article className="guide-book">
      <header className="book-head">
        <h1>{t("guide.title")}</h1>
        <p>{t("book.intro")}</p>
      </header>

      <section className="book-section">
        <h2>{t("book.dims")}</h2>
        <div className="book-dims">
          <div className="dim-card valence">
            <h3>{t("dim.valence")}</h3>
            <p className="scale">{t("guide.valence")}</p>
          </div>
          <div className="dim-card arousal">
            <h3>{t("dim.arousal")}</h3>
            <p className="scale">{t("guide.arousal")}</p>
            <p className="caveat">{t("guide.arousalNote")}</p>
          </div>
        </div>
      </section>

      <section className="book-section">
        <h2>{t("book.how")}</h2>
        <ol className="book-steps">
          <li>{t("guide.how1")}</li>
          <li>{t("guide.move")}</li>
          <li>{t("guide.how2")}</li>
        </ol>
        <div className="book-ops">
          <span><MousePointerClick size={15} /> {t("guide.opHold")}</span>
          <span><MousePointer size={15} /> {t("guide.opRelease")}</span>
          <span><CornerDownLeft size={15} /> {t("guide.opEnter")}</span>
        </div>
      </section>

      <section className="book-section">
        <h2>{t("book.modalities")}</h2>
        <p className="book-note">{t("book.modalitiesNote")}</p>
        <div className="book-modalities">
          {MODALITY_ORDER.map((modality) => {
            const Icon = ICON[modality];
            return (
              <div className="modality-card" key={modality}>
                <h3>
                  <Icon size={18} strokeWidth={1.6} />
                  {t(("modality." + modality) as Key)}
                </h3>
                <p>{t(("lead." + modality) as Key)}</p>
                <p className="watch">{t(("book.watch." + modality) as Key)}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="book-section">
        <h2>{t("book.training")}</h2>
        <ul className="book-steps">
          <li>{t("book.training1")}</li>
          <li>{t("book.training2")}</li>
          <li>{t("book.training3")}</li>
        </ul>
      </section>

      <div className="book-actions">
        <button className="primary" onClick={onStart}>
          {t(startLabel)}
        </button>
      </div>
    </article>
  );
}
