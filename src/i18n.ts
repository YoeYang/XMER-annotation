/**
 * 界面文案的三种语言。
 *
 * 默认英语：标注者来自不同语言背景，英语是唯一都能读的。中文与芬兰语
 * 供母语者切换——读母语能少一层翻译损耗，情绪词尤其如此：
 * 「无聊」和 bored 的语感差别，会直接落到标注尺度上。
 *
 * **芬兰语由我起草，需母语者复核。** 心理学术语已按文献惯例选取
 * （arousal = vireystila，valence = valenssi），但日常措辞未必地道。
 */

export type Lang = "en" | "zh" | "fi";

export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "EN" },
  { code: "zh", label: "中文" },
  { code: "fi", label: "FI" },
];

const KEY = "xmer.lang";

export function storedLang(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "en" || saved === "zh" || saved === "fi") return saved;
  } catch {
    /* 隐私模式下读不到，用默认值 */
  }
  return "en";
}

export function rememberLang(lang: Lang) {
  try {
    localStorage.setItem(KEY, lang);
  } catch {
    /* 存不住就只在本次会话生效 */
  }
}

/** 一条文案的三种写法。缺哪种就回落英语，绝不显示 key。 */
type Entry = Record<Lang, string>;

const S = {
  // ---------------------------------------------------------- 模态
  "modality.face": { en: "Face", zh: "面部", fi: "Kasvot" },
  "modality.body": { en: "Body", zh: "身体", fi: "Keho" },
  "modality.audio": { en: "Audio", zh: "音频", fi: "Ääni" },
  "modality.text": { en: "Text", zh: "文本", fi: "Teksti" },
  "modality.audiovisual": { en: "Full", zh: "完整", fi: "Koko" },

  // ---------------------------------------------------------- 维度与刻度
  "dim.valence": { en: "Valence", zh: "效价", fi: "Valenssi" },
  "dim.arousal": { en: "Arousal", zh: "唤醒", fi: "Vireystila" },
  "valence.high": { en: "Positive", zh: "正向", fi: "Myönteinen" },
  "valence.mid": { en: "Neutral", zh: "中性", fi: "Neutraali" },
  "valence.low": { en: "Negative", zh: "负向", fi: "Kielteinen" },
  // bored 取「提不起劲」这一支（Pitkästynyt），不是形容事物无趣的 Tylsä
  "arousal.high": { en: "Excited", zh: "激动", fi: "Innostunut" },
  "arousal.mid": { en: "Calm", zh: "平静", fi: "Rauhallinen" },
  "arousal.low": { en: "Bored", zh: "无聊", fi: "Pitkästynyt" },

  // ---------------------------------------------------------- 流程
  "step.familiarize": { en: "Familiarize", zh: "先熟悉", fi: "Tutustu" },
  "step.ready": { en: "Continue when ready", zh: "看懂即可继续",
                  fi: "Jatka kun olet valmis" },
  "step.next": { en: "Next", zh: "下一步", fi: "Seuraava" },
  "step.gotIt": { en: "Got it", zh: "看懂了", fi: "Selvä" },
  "step.back": { en: "Back", zh: "上一步", fi: "Edellinen" },
  "step.redo": { en: "Redo", zh: "重标", fi: "Uudelleen" },
  "step.redoHint": { en: "Redo this dimension only",
                     zh: "仅重新标注当前维度",
                     fi: "Merkitse vain tämä ulottuvuus uudelleen" },
  "step.enter": { en: "Enter", zh: "回车", fi: "Enter" },
  "step.cancel": { en: "Cancel", zh: "取消", fi: "Peruuta" },
  "step.start": { en: "Start", zh: "开始", fi: "Aloita" },

  // ---------------------------------------------------------- 采样状态
  "state.recording": { en: "Recording…", zh: "采样中…", fi: "Tallennetaan…" },
  "state.starting": { en: "Starting…", zh: "准备中…", fi: "Aloitetaan…" },
  "state.paused": { en: "Paused", zh: "已暂停", fi: "Tauolla" },
  "state.done": { en: "Done", zh: "已完成", fi: "Valmis" },
  "state.loading": { en: "Loading", zh: "加载中", fi: "Ladataan" },
  "state.readyToStart": { en: "Ready", zh: "等待开始", fi: "Valmiina" },
  "state.familiarizing": { en: "Familiarizing", zh: "熟悉中",
                           fi: "Tutustutaan" },
  "state.buffering": { en: "Buffering", zh: "缓冲中", fi: "Puskuroidaan" },
  "state.failed": { en: "Failed to load", zh: "加载失败",
                    fi: "Lataus epäonnistui" },

  // ---------------------------------------------------------- 操作提示
  "hold.hold": { en: "Hold", zh: "按住", fi: "Pidä pohjassa" },
  "hold.release": { en: "Release to pause", zh: "松开暂停", fi: "Vapauta" },
  "trace.yours": { en: "Your trace", zh: "你标的趋势", fi: "Sinun käyrä" },
  "trace.empty": { en: "Hold the bar to draw", zh: "按住后这里会画出趋势",
                   fi: "Pidä palkkia pohjassa" },

  // ---------------------------------------------------------- 侧栏
  "side.progress": { en: "Progress", zh: "总体进度", fi: "Edistyminen" },
  "side.all": { en: "All", zh: "全部", fi: "Kaikki" },
  "side.todo": { en: "Todo", zh: "未完成", fi: "Kesken" },
  "side.tasks": { en: "Tasks", zh: "任务目录", fi: "Tehtävät" },
  "side.expand": { en: "Expand sidebar", zh: "展开侧栏",
                   fi: "Laajenna sivupalkki" },
  "side.collapse": { en: "Collapse sidebar", zh: "收起侧栏",
                     fi: "Pienennä sivupalkki" },
  "side.done": { en: "Done", zh: "已完成", fi: "Valmis" },
  "side.title": { en: "Tasks", zh: "任务目录", fi: "Tehtävät" },

  // ---------------------------------------------------------- 说话人
  "speaker.rateThis": { en: "Rate this speaker", zh: "请标注这位说话人的情绪",
                        fi: "Arvioi tämän puhujan tunnetila" },
  "speaker.masked": {
    en: "Rate the body language of the person whose face is masked",
    zh: "请标注被遮住脸部的人的肢体情绪",
    fi: "Arvioi sen henkilön kehonkieltä, jonka kasvot on peitetty",
  },
  "speaker.name": { en: "Speaker", zh: "说话人", fi: "Puhuja" },
  "speaker.none": { en: "No speaker reference", zh: "未提供说话人指示",
                    fi: "Ei puhujan viitekuvaa" },
  "speaker.target": { en: "Target speaker", zh: "目标说话人",
                      fi: "Kohdepuhuja" },

  // ---------------------------------------------------------- 指南
  "guide.title": { en: "Guide", zh: "标注指南", fi: "Ohje" },
  "guide.face": { en: "Watch the target speaker's face only.",
                  zh: "只看目标说话人的面部表情。",
                  fi: "Katso vain kohdepuhujan kasvoja." },
  "guide.body": {
    en: "Watch the body language of the person whose face is masked.",
    zh: "只看被遮住脸的那个人的身体动作与姿态。",
    fi: "Katso sen henkilön kehonkieltä, jonka kasvot on peitetty.",
  },
  "guide.audio": { en: "Listen to the target speaker only.",
                   zh: "只听目标说话人的声音。",
                   fi: "Kuuntele vain kohdepuhujaa." },
  "guide.text": { en: "Judge from the text alone.",
                  zh: "只依据文字内容判断。",
                  fi: "Arvioi pelkän tekstin perusteella." },
  "guide.audiovisual": { en: "Use both picture and sound.",
                         zh: "结合画面与声音判断。",
                         fi: "Käytä sekä kuvaa että ääntä." },
  "guide.how": {
    en: "Familiarize first, then rate valence and arousal. Hold the lit bar to record, release to pause, press Enter when done.",
    zh: "先熟悉，再标效价与唤醒。按住亮起的竖条开始，松开即暂停；标完按回车继续。",
    fi: "Tutustu ensin, arvioi sitten valenssi ja vireystila. Pidä valaistua palkkia pohjassa tallentaaksesi, vapauta pysäyttääksesi, paina Enter kun olet valmis.",
  },

  // ---------------------------------------------------------- 媒体
  "media.noAudio": { en: "No audio in this modality", zh: "本模态无声音",
                     fi: "Tässä ei ole ääntä" },
  "media.slowAudio": { en: "0.1× audio may be hard to hear",
                       zh: "0.1× 音频可能难以听清",
                       fi: "0.1× ääni voi olla vaikea kuulla" },
  "media.textLoading": { en: "Loading…", zh: "载入中…", fi: "Ladataan…" },
  "media.textFailed": { en: "Failed to load text", zh: "文本加载失败",
                        fi: "Tekstin lataus epäonnistui" },

  // ---------------------------------------------------------- 错误
  "err.noToken": {
    en: "Missing access token — please open the personal link you were given.",
    zh: "缺少访问令牌，请用研究者发给你的专属网址打开。",
    fi: "Käyttötunnus puuttuu — avaa sinulle annettu henkilökohtainen linkki.",
  },
  "err.badToken": {
    en: "Token invalid or disabled — ask the researcher for a new link.",
    zh: "访问令牌无效或已停用，请向研究者索取新链接。",
    fi: "Tunnus on virheellinen tai poistettu käytöstä — pyydä tutkijalta uusi linkki.",
  },
  "err.offline": {
    en: "Cannot reach the server — please try again.",
    zh: "无法连接标注服务器，请稍后重试。",
    fi: "Palvelimeen ei saada yhteyttä — yritä myöhemmin uudelleen.",
  },
  "err.workspace": { en: "Failed to load workspace", zh: "标注工作区读取失败",
                     fi: "Työtilan lataus epäonnistui" },
  "err.retry": { en: "Something went wrong, please try again",
                 zh: "操作失败，请重试",
                 fi: "Toiminto epäonnistui, yritä uudelleen" },
  "err.localStorage": {
    en: "Local storage failed — check your browser settings and reload",
    zh: "本机存储写入失败，请检查浏览器设置后刷新",
    fi: "Paikallinen tallennus epäonnistui — tarkista selaimen asetukset ja lataa sivu uudelleen",
  },

  // ---------------------------------------------------------- 播放控件
  "player.play": { en: "Play", zh: "播放媒体", fi: "Toista" },
  "player.pause": { en: "Pause", zh: "暂停媒体", fi: "Tauko" },
  "player.progress": { en: "Playback position", zh: "媒体播放进度",
                       fi: "Toiston kohta" },
  "player.unmute": { en: "Unmute", zh: "打开声音", fi: "Poista mykistys" },
  "player.mute": { en: "Mute", zh: "静音", fi: "Mykistä" },
  "player.rate": { en: "Playback speed", zh: "播放速度", fi: "Toistonopeus" },
  "player.reload": { en: "Reload", zh: "重新加载", fi: "Lataa uudelleen" },
  "player.familiarizeArea": { en: "Familiarize", zh: "熟悉材料",
                              fi: "Tutustu aineistoon" },

  // ---------------------------------------------------------- 其它提示
  "app.title": { en: "XMER Annotation", zh: "XMER 标注工作台",
                 fi: "XMER-merkintätyökalu" },
  "app.refreshHint": {
    en: "Refresh this page once tasks are assigned.",
    zh: "分配完成后刷新本页即可开始。",
    fi: "Päivitä sivu, kun tehtävät on jaettu.",
  },
  "app.loadingWorkspace": { en: "Loading your workspace…",
                            zh: "正在读取你的标注工作区…",
                            fi: "Ladataan työtilaasi…" },
  "app.noTasks": { en: "No tasks assigned yet.",
                   zh: "研究者尚未给你分配任务。",
                   fi: "Sinulle ei ole vielä annettu tehtäviä." },
  "err.needSecure": {
    en: "Please open via localhost or HTTPS in a modern browser that supports Web Locks.",
    zh: "请通过 localhost 或 HTTPS 打开，并使用支持 Web Locks 的现代浏览器。",
    fi: "Avaa sivu localhostin tai HTTPS:n kautta selaimella, joka tukee Web Locks -rajapintaa.",
  },
  "err.otherTab": {
    en: "Another tab is using the local workspace — close it and reload.",
    zh: "另一个页面正在使用本地工作区，请关闭该页面后重新加载。",
    fi: "Toinen välilehti käyttää paikallista työtilaa — sulje se ja lataa sivu uudelleen.",
  },
  "err.rememberTask": {
    en: "Could not remember the current task; your annotations are still saved locally.",
    zh: "无法记住当前任务；标注结果仍会保存在本地数据库。",
    fi: "Nykyistä tehtävää ei voitu muistaa; merkinnät tallentuvat silti paikallisesti.",
  },
  "err.saveRound": {
    en: "Could not save this round — please try again shortly.",
    zh: "当前轮次保存失败，请稍后重试。",
    fi: "Tämän kierroksen tallennus epäonnistui — yritä hetken kuluttua uudelleen.",
  },
  "err.waitSave": {
    en: "Please wait for the current save to finish.",
    zh: "请先等待当前记录保存完成。",
    fi: "Odota, että nykyinen tallennus valmistuu.",
  },

  // ---------------------------------------------------------- 语言切换
  "lang.label": { en: "Language", zh: "语言", fi: "Kieli" },
} satisfies Record<string, Entry>;

export type Key = keyof typeof S;

export function translate(lang: Lang, key: Key): string {
  const entry = S[key] as Entry;
  // 回落英语而不是显示 key：漏翻一条只是读着别扭，露出 key 才是出丑
  return entry[lang] || entry.en;
}
