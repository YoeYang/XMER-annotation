import { Languages } from "lucide-react";
import { useLang } from "../LangContext";
import { LANGS } from "../i18n";

/** 右上角的语言切换。三种语言直接并排，少一次点击。 */
export default function LangSwitch() {
  const { lang, setLang, t } = useLang();
  return (
    <div className="lang-switch" role="group" aria-label={t("lang.label")}>
      <Languages size={15} aria-hidden="true" />
      {LANGS.map((item) => (
        <button
          key={item.code}
          type="button"
          aria-pressed={lang === item.code}
          className={lang === item.code ? "active" : ""}
          onClick={() => setLang(item.code)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
