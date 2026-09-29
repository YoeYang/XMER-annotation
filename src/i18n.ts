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

  // ------------------------------------------------------------ 指南页
  // 与标注时那个弹窗分工不同：弹窗只讲当前模态，这一页把五个摆在一起，
  // 让人看见它们的区别——那正是这个数据集要研究的东西。
  "book.intro": {
    en: "You will rate how a speaker's emotion changes over time, on two "
      + "dimensions, from five different kinds of material. Read this page "
      + "once before you start; you can reopen it at any time.",
    zh: "你要在两个维度上，连续标注说话人的情绪随时间的变化，材料有五种。"
      + "开始前先看一遍这一页，之后随时可以再打开。",
    fi: "Arvioit puhujan tunnetilan muutoksia ajassa kahdella ulottuvuudella "
      + "viidenlaisesta aineistosta. Lue tämä sivu kerran ennen aloitusta; "
      + "voit avata sen uudelleen milloin tahansa.",
  },
  "book.dims": { en: "The two dimensions", zh: "两个维度",
                 fi: "Kaksi ulottuvuutta" },
  "book.how": { en: "How to rate", zh: "怎么操作", fi: "Näin merkitset" },
  "book.modalities": { en: "The five kinds of material", zh: "五种材料",
                       fi: "Viisi aineistotyyppiä" },
  "book.modalitiesNote": {
    en: "The same clip is rated five times, each time from one kind of "
      + "material only. Ratings that differ between them are expected — "
      + "that difference is exactly what this study measures. Never fill in "
      + "from what another round showed you.",
    zh: "同一段素材会被标五遍，每遍只依据其中一种材料。几遍之间标得不一样是"
      + "正常的——那个差异正是这项研究要测量的。**不要拿别的轮次看到的东西"
      + "来补全这一轮。**",
    fi: "Sama klippi arvioidaan viidesti, joka kerta vain yhdentyyppisestä "
      + "aineistosta. On odotettavaa että arviot eroavat toisistaan — juuri "
      + "sitä eroa tämä tutkimus mittaa. Älä koskaan täydennä sillä, mitä "
      + "jokin toinen kierros näytti.",
  },
  "book.watch.face": {
    en: "Stretches where the target speaker cannot be identified are blacked "
      + "out. That is normal — rate what you can see, and hold the line "
      + "steady through the gap.",
    zh: "认不出指定说话人的时段是黑屏，那是正常的。看得见什么标什么，"
      + "黑屏期间把线保持住。",
    fi: "Jaksot joissa kohdepuhujaa ei tunnisteta ovat mustia. Se on normaalia "
      + "— arvioi sen perusteella minkä näet, ja pidä viiva vakaana aukon yli.",
  },
  "book.watch.body": {
    en: "The face is masked on purpose. Read gesture, posture and body "
      + "tension. Where the body is ambiguous, different annotators may "
      + "reasonably disagree — rate your own reading.",
    zh: "脸是故意遮住的。看手势、姿态和身体的紧张程度。肢体本身含糊时，"
      + "不同标注者读出不同结果是合理的——标你自己的判断。",
    fi: "Kasvot on peitetty tarkoituksella. Lue eleet, asento ja kehon "
      + "jännitys. Kun keho on monitulkintainen, merkitsijät voivat "
      + "perustellusti olla eri mieltä — merkitse oma tulkintasi.",
  },
  "book.watch.audio": {
    en: "Follow the main speaker — the one who speaks longest. Other voices, "
      + "laughter and music in the background are not what you are rating.",
    zh: "跟住主要说话人，也就是说话时长最长的那个。背景里的其他人声、"
      + "笑声和音乐不是你要标的对象。",
    fi: "Seuraa pääpuhujaa — sitä joka puhuu pisimpään. Taustan muut äänet, "
      + "naurut ja musiikki eivät ole arvioinnin kohde.",
  },
  "book.watch.text": {
    en: "Rate at the pace the words light up, not after reading the whole "
      + "sentence. A word can flip the reading of everything before it — let "
      + "the line turn when it does.",
    zh: "跟着文字点亮的节奏标，不要读完整句再一次拉到位。一个词可能推翻"
      + "前面所有的判断——它出现时，线就跟着转。",
    fi: "Merkitse siinä tahdissa kuin sanat syttyvät, älä koko lauseen "
      + "luettuasi. Yksi sana voi kääntää kaiken aiemman — anna viivan "
      + "kääntyä silloin.",
  },
  "book.watch.audiovisual": {
    en: "Here picture, voice and words are all available. The full clip can "
      + "show what no single channel does — a line that reads as harsh may "
      + "turn out to be a joke between friends.",
    zh: "这一轮画面、声音、文字都可以用。完整片段能看到任何单一通道看不到的"
      + "东西——听起来刻薄的一句，可能是朋友间的玩笑。",
    fi: "Tässä kuva, ääni ja sanat ovat kaikki käytettävissä. Koko klippi voi "
      + "näyttää sen mitä yksikään yksittäinen kanava ei — töykeältä "
      + "kuulostava repliikki voi osoittautua ystävien väliseksi vitsiksi.",
  },
  "book.training": { en: "How the training works", zh: "训练怎么进行",
                     fi: "Näin harjoittelu etenee" },
  "book.training1": {
    en: "Each clip is rated twice: first valence, then arousal.",
    zh: "每个片段标两遍：先效价，再唤醒。",
    fi: "Jokainen klippi arvioidaan kahdesti: ensin valenssi, sitten vireystila.",
  },
  "book.training2": {
    en: "Once both are submitted, your curve is shown against a reference "
      + "curve, with a short note on how the reference was read.",
    zh: "两个维度都提交之后，会把你的曲线和参考曲线画在一起，"
      + "并附一段参考曲线的判断依据。",
    fi: "Kun molemmat on lähetetty, käyräsi näytetään viitekäyrän rinnalla, "
      + "mukana lyhyt selostus siitä miten viite luettiin.",
  },
  "book.training3": {
    en: "Differences are not mistakes. What matters is that you follow the "
      + "changes at all, and use the range rather than parking the line.",
    zh: "标得不一样不等于标错了。要紧的是你确实跟着变化走，"
      + "并且用上整个量程，而不是把线摆在一处不动。",
    fi: "Erot eivät ole virheitä. Tärkeää on että todella seuraat muutoksia ja "
      + "käytät koko asteikkoa etkä jätä viivaa paikalleen.",
  },
  "book.start": { en: "Start", zh: "开始标注", fi: "Aloita" },
  "book.reopen": { en: "Guide", zh: "指南", fi: "Ohje" },
  "book.close": { en: "Back to annotation", zh: "返回标注",
                  fi: "Takaisin merkintään" },

  // ------------------------------------------------------------ 分段复盘
  "debrief.title": { en: "How you rated", zh: "你标得怎么样",
                     fi: "Näin arvioit" },
  "debrief.lead": {
    en: "Your curve against the reference for this block.",
    zh: "这一段里，你的曲线与参考曲线的对照。",
    fi: "Käyräsi viitekäyrän rinnalla tässä osiossa.",
  },
  "debrief.mine": { en: "Yours (solid)", zh: "你标的（实线）",
                    fi: "Sinun (yhtenäinen)" },
  "debrief.reference": { en: "Reference (dashed)", zh: "参考（虚线）",
                         fi: "Viite (katkoviiva)" },
  "debrief.continue": { en: "Continue", zh: "继续", fi: "Jatka" },
  "debrief.close": { en: "Close", zh: "关闭", fi: "Sulje" },
  "debrief.loading": { en: "Loading…", zh: "载入中…", fi: "Ladataan…" },
  "debrief.failed": {
    en: "Could not load the comparison.",
    zh: "对比载入失败。",
    fi: "Vertailua ei voitu ladata.",
  },
  "debrief.review": { en: "Compare", zh: "看对比", fi: "Vertaa" },

  // 正式阶段回看训练（只读）
  "review.open": { en: "Training review", zh: "训练回顾", fi: "Harjoittelun kertaus" },
  "review.title": { en: "Look back at your training", zh: "回看训练",
                    fi: "Katso harjoittelua uudelleen" },
  "review.lead": {
    en: "Pick a material to see the training clips, the curves you drew, "
      + "the reference curves and the explanations. This is read-only and "
      + "does not affect your annotation tasks.",
    zh: "选一种材料，查看训练素材、你当时标的曲线、参考曲线和解释。只能查看，不影响正式标注。",
    fi: "Valitse materiaali nähdäksesi harjoitusklipit, piirtämäsi käyrät, "
      + "vertailukäyrät ja selitykset. Vain luettavissa, ei vaikuta merkintätehtäviin.",
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

  // 模态提示：常驻在媒体上方，说清这一轮「凭什么判断」。
  // 写在界面上而不是只写在指南里——指南只在开头看一次，
  // 标到第三百条时人早就按自己的习惯走了。
  "hint.audio": {
    en: "Judge only from the main speaker's prosody — rate, intonation, "
      + "volume, stress. Ignore background voices, music and other noise.",
    zh: "仅依据主要说话人的语速、语调、音量、重音等 prosody 判断，"
      + "忽略背景人声、背景音乐等干扰。",
    fi: "Arvioi vain pääpuhujan prosodiasta: puhenopeus, intonaatio, "
      + "voimakkuus, painotus. Jätä taustaäänet ja musiikki huomiotta.",
  },
  "hint.text": {
    en: "Annotate at the pace the words light up.",
    zh: "跟着文字点亮的节奏标注。",
    fi: "Merkitse siinä tahdissa kuin sanat syttyvät.",
  },

  // 收尾页
  "done.title": {
    en: "All done — thank you!",
    zh: "全部标注完成，辛苦了！",
    fi: "Kaikki valmista — kiitos!",
  },
  "done.count": {
    en: "subtasks completed",
    zh: "个子任务已完成",
    fi: "osatehtävää valmiina",
  },
  "done.body": {
    en: "Every subtask has both valence and arousal submitted. "
      + "Nothing is left open — you can close this page.",
    zh: "每个子任务的效价与唤醒都已提交，没有遗漏，可以关闭页面了。",
    fi: "Jokaisesta osatehtävästä on lähetetty sekä valenssi että vireystila. "
      + "Mitään ei jäänyt kesken — voit sulkea sivun.",
  },
  "done.back": {
    en: "Back to the list",
    zh: "返回任务目录",
    fi: "Takaisin luetteloon",
  },
  "done.trainingTitle": {
    en: "Training complete — well done!",
    zh: "训练完成，辛苦了！",
    fi: "Harjoittelu valmis — hienoa!",
  },
  "done.trainingBody": {
    en: "Your annotation tasks are now unlocked. They come in blocks by material: "
      + "all faces first, then bodies, audio, text and full videos.",
    zh: "正式标注任务已经解锁。任务按材料分块：先是全部面部，再依次是身体、音频、文本和完整视频。",
    fi: "Varsinaiset merkintätehtävät ovat nyt auki. Ne tulevat lohkoina materiaalin mukaan: "
      + "ensin kaikki kasvot, sitten vartalo, ääni, teksti ja kokonaiset videot.",
  },
  "done.startMain": {
    en: "Start annotating",
    zh: "开始正式标注",
    fi: "Aloita merkitseminen",
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
