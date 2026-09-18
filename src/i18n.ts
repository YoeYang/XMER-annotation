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
  // 滑条端点只有一个词，用「兴奋 / Innostunut」会把唤醒轴往正向情绪上带——
  // 高唤醒既可能是狂喜也可能是暴怒。端点说强度，具体情绪留给指南去举例。
  "arousal.high": { en: "High arousal", zh: "高唤醒", fi: "Korkea vireystila" },
  "arousal.mid": { en: "Calm", zh: "平静", fi: "Rauhallinen" },
  "arousal.low": { en: "Low arousal", zh: "低唤醒", fi: "Matala vireystila" },

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
  "trace.yours": { en: "Your trace", zh: "你标的趋势", fi: "Sinun käyräsi" },
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
  "guide.title": { en: "Annotation Guide", zh: "情绪标注指南",
                   fi: "Merkintäohje" },

  // 导语：各模态看的东西不同，这一句是整份指南里最要紧的
  "lead.face": {
    en: "Identify the target speaker from the reference photo, then rate their emotion continuously from facial expression alone.",
    zh: "请根据头像确认指定说话人，仅依据其面部表情，连续标注情绪变化。",
    fi: "Tunnista kohdepuhuja viitekuvasta ja arvioi hänen tunnetilaansa jatkuvasti pelkkien ilmeiden perusteella.",
  },
  "lead.body": {
    en: "Rate the person whose face is masked, continuously, from body movement and posture alone.",
    zh: "请标注被遮住脸部的那个人，仅依据其肢体动作与姿态，连续标注情绪变化。",
    fi: "Arvioi jatkuvasti sitä henkilöä, jonka kasvot on peitetty, pelkän kehonliikkeen ja asennon perusteella.",
  },
  "lead.audio": {
    en: "Judge the speaker's changing emotion from prosody alone — speech rate, intonation, loudness, stress.",
    zh: "仅根据音频材料中的语速、语调、音量、重音等 prosody 元素，判断说话者连续的情感变化。",
    fi: "Arvioi puhujan tunnetilan muutoksia pelkän prosodian perusteella — puhenopeus, intonaatio, äänenvoimakkuus, painotus.",
  },
  "lead.text": {
    en: "Rate the emotion continuously from the meaning the words convey, as they appear.",
    zh: "仅依据逐词呈现的文字所表达的语义信息，连续标注情绪变化。",
    fi: "Arvioi tunnetilaa jatkuvasti sanojen välittämän merkityksen perusteella sitä mukaa kun ne ilmestyvät.",
  },
  "lead.audiovisual": {
    en: "Identify the target speaker from the reference photo, then rate their emotion continuously using both picture and sound.",
    zh: "请根据头像确认指定说话人，结合画面与声音，连续标注情绪变化。",
    fi: "Tunnista kohdepuhuja viitekuvasta ja arvioi hänen tunnetilaansa jatkuvasti sekä kuvan että äänen perusteella.",
  },

  "guide.dims": { en: "Dimensions", zh: "标注维度", fi: "Ulottuvuudet" },
  "guide.valence": {
    en: "−1 negative (sad, angry) · 0 neutral · +1 positive (happy, cheerful)",
    zh: "−1 负向（难过、生气）· 0 中性 · +1 正向（开心、快乐）",
    fi: "−1 kielteinen (surullinen, vihainen) · 0 neutraali · +1 myönteinen (iloinen)",
  },
  // 「无聊」在这里是 pitkästynyt（提不起劲），不是 tylsä（事物无趣）
  "guide.arousal": {
    en: "−1 bored, not engaged · 0 calmly talking · +1 highly excited or tense",
    zh: "−1 无聊、注意力不在对话上 · 0 平静地交谈 · +1 高度兴奋或紧张",
    fi: "−1 pitkästynyt, huomio ei kohdistu keskusteluun · 0 puhuja keskustelee rauhallisesti · +1 hyvin innostunut tai jännittynyt",
  },
  "guide.arousalNote": {
    en: "Arousal is independent of whether the emotion is positive or negative.",
    zh: "唤醒程度与情绪正负无关。",
    fi: "Vireystila on riippumaton siitä, onko tunne myönteinen vai kielteinen.",
  },

  "guide.how": { en: "How to rate", zh: "如何标注", fi: "Näin merkitset" },
  "guide.how1": {
    en: "Familiarize yourself with the clip first. Then rate valence, and after that arousal.",
    zh: "先熟悉片段。先标效价，再标唤醒。",
    fi: "Tutustu ensin klippiin. Arvioi sitten ensin valenssi ja sen jälkeen vireystila.",
  },
  "guide.how2": {
    en: "Rate each dimension across the whole clip. You can move to the next step only once the current dimension is finished. Playback speed is adjustable, and you can redo the current dimension at any time.",
    zh: "每个维度都要标完整个片段。当前维度标完，才能进入下一步。播放速度可调，当前维度可随时重标。",
    fi: "Arvioi kumpikin ulottuvuus koko klipin ajalta. Voit siirtyä seuraavaan vaiheeseen vasta, kun nykyisen ulottuvuuden arviointi on valmis. Toistonopeutta voi säätää, ja nykyisen ulottuvuuden arvioinnin voi tehdä uudelleen milloin tahansa.",
  },

  "guide.status": { en: "Status", zh: "状态与提示", fi: "Tila" },
  "guide.status1": {
    en: "A ✓ on a sample means it is finished and uploaded. If the page seems stuck, click Redo.",
    zh: "样本显示 ✓，表示标注已完成并上传。页面卡住时，点击「重标」。",
    fi: "Näytteen ✓ tarkoittaa, että merkintä on valmis ja lähetetty. Jos sivu jumittuu, napsauta Uudelleen.",
  },

  // 只说「按住」不够：不移动鼠标就只是一条直线，人以为自己在标其实没标
  "guide.move": {
    en: "Hold the left mouse button on the rating bar and move the mouse up or down as the speaker's emotion changes. Releasing the button pauses both playback and rating.",
    zh: "在标注条上按住鼠标左键，随说话人情绪的变化上下移动鼠标。松开按键，播放与标注同时暂停。",
    fi: "Pidä hiiren vasen painike painettuna arviointipalkin päällä ja liikuta hiirtä ylös tai alas puhujan tunnetilan muuttuessa. Kun vapautat painikkeen, toisto ja arviointi keskeytyvät.",
  },

  "guide.opHold": { en: "Hold left button — record", zh: "按住左键：标注",
                    fi: "Pidä hiiren vasen painike painettuna — tallenna" },
  "guide.opRelease": { en: "Release — pause", zh: "松开左键：暂停",
                       fi: "Vapauta — tauko" },
  "guide.opEnter": { en: "Enter — next step", zh: "回车：下一步",
                     fi: "Enter — seuraava" },

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
