import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { rememberLang, storedLang, translate } from "./i18n";
import type { Key, Lang } from "./i18n";

interface LangValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: Key) => string;
}

/**
 * 界面语言。默认英语，选择记在浏览器里。
 *
 * 用 Context 而不是逐层传 props：文案散在每个组件里，靠 props 传要把
 * 整棵树都改成接力棒。
 */
const Ctx = createContext<LangValue>({
  lang: "en",
  setLang: () => {},
  t: (key) => translate("en", key),
});

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => storedLang());
  const value = useMemo<LangValue>(
    () => ({
      lang,
      setLang: (next: Lang) => {
        setLangState(next);
        rememberLang(next);
      },
      t: (key: Key) => translate(lang, key),
    }),
    [lang],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLang() {
  return useContext(Ctx);
}
