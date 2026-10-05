import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  Database,
  FileText,
  Focus,
  Layers3,
  ListChecks,
  LoaderCircle,
  LockKeyhole,
  Play,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Video,
  X,
} from "lucide-react";
import {
  Annotation,
  api,
  blankAnnotation,
  blankRatings,
  Channel,
  channels,
  Dimension,
  dimensions,
  Ratings,
  Sample,
} from "./data";
import "./styles.css";

const steps = ["场景核对", "CPM 评分", "冲突证据", "动态与提交"];
const cardFields = [
  {
    key: "subject",
    label: "目标主体",
    hint: "用身份或画面位置明确正在标注的人",
  },
  { key: "event", label: "可观察事件", hint: "记录发生或被明确提及的事" },
  { key: "goal", label: "可辨认目标", hint: "仅保留有明确线索支持的目标" },
  {
    key: "role",
    label: "可辨认角色",
    hint: "核对身份或交互关系，不推断内心动机",
  },
] as const;
type AdminData = {
  counts: {
    annotator: string;
    total: number;
    submitted: number;
    draft: number;
  }[];
  recent: {
    id: number;
    task_id: string;
    attempt_no: number;
    status: string;
    created_at: string;
  }[];
  schema: string;
  sample_count: number;
};

function WindowInput({
  value,
  onChange,
  duration,
  current,
}: {
  value: number[];
  onChange: (v: number[]) => void;
  duration: number;
  current?: number;
}) {
  return (
    <div className="window-input">
      <label>
        起始{" "}
        <input
          aria-label="区间起始秒数"
          type="number"
          min="0"
          max={duration}
          step="0.1"
          value={value[0]}
          onChange={(e) => onChange([Number(e.target.value), value[1]])}
        />
        <span>s</span>
      </label>
      <span className="muted">—</span>
      <label>
        结束{" "}
        <input
          aria-label="区间结束秒数"
          type="number"
          min="0"
          max={duration}
          step="0.1"
          value={value[1]}
          onChange={(e) => onChange([value[0], Number(e.target.value)])}
        />
        <span>s</span>
      </label>
      {current !== undefined && (
        <button
          className="text-button"
          onClick={() => onChange([Number(current.toFixed(2)), value[1]])}
        >
          <Focus size={14} />
          用当前时间作起点
        </button>
      )}
    </div>
  );
}

function Choices({
  value,
  options,
  onChange,
}: {
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
}) {
  return (
    <div className="choices">
      {options.map(([id, label]) => (
        <button
          key={id}
          className={value === id ? "choice selected" : "choice"}
          aria-pressed={value === id}
          onClick={() => onChange(id)}
        >
          <span className="radio-dot" />
          {label}
        </button>
      ))}
    </div>
  );
}

function ChannelChoices({
  values,
  onChange,
}: {
  values: Channel[];
  onChange: (v: Channel[]) => void;
}) {
  return (
    <div className="channel-choices">
      {(Object.keys(channels) as Channel[]).map((key) => (
        <button
          key={key}
          className={values.includes(key) ? "chip active" : "chip"}
          onClick={() =>
            onChange(
              values.includes(key)
                ? values.filter((v) => v !== key)
                : [...values, key],
            )
          }
        >
          {values.includes(key) && <Check size={13} />}
          {channels[key]}
        </button>
      ))}
    </div>
  );
}

function RatingFields({
  ratings,
  onChange,
  evidence,
}: {
  ratings: Ratings;
  onChange: (r: Ratings) => void;
  evidence: Annotation["evidence"];
}) {
  const verified = evidence.filter((e) => e.verified && e.observation.trim());
  const update = (id: Dimension, value: Partial<Ratings[Dimension]>) =>
    onChange({ ...ratings, [id]: { ...ratings[id], ...value } });
  return (
    <>
      {dimensions.map((dim) => (
        <article className="rating-card" key={dim.id}>
          <div className="rating-heading">
            <span className={`dimension dimension-${dim.id}`}>{dim.id}</span>
            <div>
              <h3>{dim.name}</h3>
              <p>{dim.question}</p>
            </div>
          </div>
          <div className="rating-options">
            {dim.anchors.map((anchor, index) => (
              <button
                key={anchor}
                aria-pressed={
                  ratings[dim.id].state === "known" &&
                  ratings[dim.id].value === index - 2
                }
                className={
                  ratings[dim.id].state === "known" &&
                  ratings[dim.id].value === index - 2
                    ? "selected"
                    : ""
                }
                onClick={() =>
                  update(dim.id, { state: "known", value: index - 2 })
                }
              >
                <strong>
                  {index > 2 ? "+" : ""}
                  {index - 2}
                </strong>
                <span>{anchor}</span>
              </button>
            ))}
            <button
              className={`unknown ${ratings[dim.id].state === "unknown" ? "selected" : ""}`}
              onClick={() =>
                update(dim.id, {
                  state: "unknown",
                  value: null,
                  evidence_ids: [],
                })
              }
            >
              <strong>?</strong>
              <span>信息不足</span>
            </button>
          </div>
          <p className="rating-hint">
            <CircleHelp size={13} />
            {dim.hint}
          </p>
          {ratings[dim.id].state === "known" && (
            <div className="rating-evidence">
              <span>
                关联依据 <b>*</b>
              </span>
              {verified.length === 0 ? (
                <small>先在左侧核对至少一条证据。</small>
              ) : (
                verified.map((e) => (
                  <label key={e.id}>
                    <input
                      type="checkbox"
                      checked={ratings[dim.id].evidence_ids.includes(e.id)}
                      onChange={(event) =>
                        update(dim.id, {
                          evidence_ids: event.target.checked
                            ? [...ratings[dim.id].evidence_ids, e.id]
                            : ratings[dim.id].evidence_ids.filter(
                                (id) => id !== e.id,
                              ),
                        })
                      }
                    />
                    {e.id} · {channels[e.modality]}
                  </label>
                ))
              )}
            </div>
          )}
          <label className="check-label mixed">
            <input
              type="checkbox"
              checked={ratings[dim.id].mixed}
              onChange={(e) => update(dim.id, { mixed: e.target.checked })}
            />
            存在混合评价
          </label>
          {ratings[dim.id].mixed && (
            <input
              className="full-input"
              placeholder="简述相反目标或混合后果，不用 0 代替混合评价"
              value={ratings[dim.id].note}
              onChange={(e) => update(dim.id, { note: e.target.value })}
            />
          )}
        </article>
      ))}
    </>
  );
}

function App() {
  const [page, setPage] = useState<"work" | "admin">("work");
  const [annotator, setAnnotator] = useState("CPM-01");
  const [samples, setSamples] = useState<Sample[]>([]);
  const [clip, setClip] = useState("CPM-S0001");
  const [doc, setDoc] = useState<Annotation | null>(null);
  const [step, setStep] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("尚未保存");
  const [error, setError] = useState("");
  const [guide, setGuide] = useState(false);
  const [admin, setAdmin] = useState<AdminData | null>(null);
  const [adminPage, setAdminPage] = useState(0);
  const [current, setCurrent] = useState(0);
  const [mediaError, setMediaError] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const sample = samples.find((s) => s.clip_id === clip);
  const draftKey = `xmer-cpm-v1:${annotator}:${clip}`;
  const done = samples.filter((s) => s.status === "submitted").length;
  const filtered = samples.filter(
    (s) =>
      s.clip_id.toLowerCase().includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "todo" ? !s.status : s.status === filter)),
  );

  useEffect(() => {
    let active = true;
    setSamples([]);
    setDoc(null);
    setError("");
    api<Sample[]>(`samples?annotator=${annotator}`)
      .then((data) => {
        if (active) setSamples(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [annotator]);

  useEffect(() => {
    if (!sample) return;
    let active = true;
    setDoc(null);
    setCurrent(0);
    setMediaError(false);
    setDirty(false);
    setError("");
    api<{ payload: Annotation; status: string; attempt_no: number } | null>(
      `record?annotator=${annotator}&clip=${clip}`,
    )
      .then((record) => {
        if (!active) return;
        let recovered: Annotation | null = null;
        try {
          const cached = localStorage.getItem(draftKey);
          if (cached) recovered = JSON.parse(cached);
        } catch {
          /* Database record remains the recovery source. */
        }
        setDoc(recovered || record?.payload || blankAnnotation(sample));
        setDirty(!!recovered);
        setSaveMessage(
          recovered
            ? "已恢复本机草稿 · 待存入数据库"
            : record
              ? `${record.status === "submitted" ? "已提交" : "已存草稿"} · 版本 ${record.attempt_no}`
              : "尚未保存",
        );
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [annotator, clip, !!sample]);

  useEffect(() => {
    if (page === "admin")
      api<AdminData>("admin")
        .then(setAdmin)
        .catch((e) => setError(e.message));
  }, [page, saveMessage]);

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  function edit(next: Annotation) {
    setDoc(next);
    setDirty(true);
    setSaveMessage("本机草稿已暂存");
    try {
      localStorage.setItem(draftKey, JSON.stringify(next));
    } catch {
      setSaveMessage("本机暂存失败，请保存草稿");
    }
  }
  function patch(next: Partial<Annotation>) {
    if (doc) edit({ ...doc, ...next });
  }
  function changeClip(next: string) {
    if (saving) return;
    setClip(next);
    setStep(0);
    content.current?.scrollTo(0, 0);
  }
  function seek(time: number) {
    if (video.current) {
      video.current.currentTime = time;
      setCurrent(video.current.currentTime);
    }
  }
  function goStep(next: number) {
    setStep(next);
    content.current?.scrollTo({ top: 0, behavior: "smooth" });
  }
  async function save(status: "draft" | "submitted") {
    if (!doc || !sample || saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await api<{
        attempt_no: number;
        status: "draft" | "submitted";
      }>("record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ annotator, clip, status, payload: doc }),
      });
      localStorage.removeItem(draftKey);
      setDirty(false);
      setSaveMessage(
        `${status === "submitted" ? "已提交" : "草稿已存入数据库"} · 版本 ${result.attempt_no}`,
      );
      setSamples((old) =>
        old.map((s) =>
          s.clip_id === clip
            ? { ...s, status, attempt_no: result.attempt_no }
            : s,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function exportData() {
    try {
      const data = await api<object>("export");
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `CPM-demo-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Layers3 size={23} />
          </div>
          <div>
            XMER<span>MULTIMODAL RESEARCH</span>
          </div>
        </div>
        <div className="workspace-caption">研究工作空间</div>
        <div className="project-switch">
          <div className="project-icon">C</div>
          <div>
            <strong>CPM标注</strong>
            <span>认知评价 · 证据核对</span>
          </div>
          <ChevronDown size={15} />
        </div>
        <nav>
          <button
            className={page === "work" ? "nav-item active" : "nav-item"}
            onClick={() => setPage("work")}
          >
            <ClipboardCheck size={18} />
            标注工作台
            <span className="nav-dot" />
          </button>
          <button
            className={page === "admin" ? "nav-item active" : "nav-item"}
            onClick={() => setPage("admin")}
          >
            <Database size={18} />
            样本与数据管理
          </button>
          <button className="nav-item" onClick={() => setGuide(true)}>
            <BookOpen size={18} />
            标注指南
            <ArrowRight size={14} />
          </button>
        </nav>
        <div className="sidebar-divider" />
        <div className="queue-heading">
          <span>当前子集</span>
          <span className="count">360</span>
        </div>
        <div className="subset-name">
          CPM 试标子集 <span>v1</span>
        </div>
        <p className="sidebar-note">同一子集 · 两位标注者独立全量标注</p>
        <div className="queue-progress">
          <div>
            <strong>{done}</strong>
            <span>/ 360 已完成</span>
            <b>{Math.round((done / 360) * 100)}%</b>
          </div>
          <div className="progress-track">
            <i style={{ width: `${(done / 360) * 100}%` }} />
          </div>
        </div>
        <label className="search">
          <Search size={15} />
          <input
            aria-label="搜索样本"
            placeholder="搜索样本编号"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setAdminPage(0);
            }}
          />
          <span>⌕</span>
        </label>
        <div className="queue-tabs">
          {[
            ["all", "全部"],
            ["todo", "待标注"],
            ["submitted", "已完成"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={filter === id ? "selected" : ""}
              onClick={() => {
                setFilter(id);
                setAdminPage(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="sample-list">
          {filtered.slice(0, 80).map((s) => (
            <button
              key={s.clip_id}
              disabled={saving}
              className={clip === s.clip_id ? "sample active" : "sample"}
              onClick={() => {
                changeClip(s.clip_id);
                setPage("work");
              }}
            >
              <span
                className={
                  s.status === "submitted"
                    ? "sample-state complete"
                    : s.status === "draft"
                      ? "sample-state draft"
                      : "sample-state"
                }
              >
                {s.status === "submitted" ? (
                  <Check size={12} />
                ) : s.status === "draft" ? (
                  "·"
                ) : (
                  ""
                )}
              </span>
              <span>
                {s.clip_id}
                <small>{s.original_card.event.slice(0, 15)}…</small>
              </span>
              {s.clip_id === clip && <span className="current-tag">当前</span>}
            </button>
          ))}
          {filtered.length > 80 && (
            <p className="sidebar-note">显示前 80 条 · 管理页可浏览全部</p>
          )}
          {filtered.length === 0 && (
            <p className="sidebar-note">没有匹配的样本</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="va-project">
            <span className="va-icon">VA</span>
            <div>
              <strong>VA标注</strong>
              <small>连续效价 / 唤醒标注</small>
            </div>
            <span className="live-dot" />
          </div>
          <p>
            <ShieldCheck size={13} />
            独立工作空间 · VA 标注进行中
          </p>
        </div>
      </aside>

      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间 <ChevronRight size={14} />
            <strong>CPM标注</strong>
            <span className="demo-badge">模拟数据预览</span>
          </div>
          <div className="topbar-right">
            <span className="local-status">
              <i />
              本地试标环境
            </span>
            <span className="avatar">{annotator.slice(-2)}</span>
            <select
              aria-label="切换模拟标注者"
              disabled={saving}
              value={annotator}
              onChange={(e) => {
                setAnnotator(e.target.value);
                setStep(0);
              }}
            >
              <option>CPM-01</option>
              <option>CPM-02</option>
            </select>
          </div>
        </header>
        {error && (
          <div role="alert" className="error-banner">
            <span>{error}</span>
            <button aria-label="关闭错误" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {page === "work" ? (
          <>
            <div className="page-heading">
              <div>
                <div className="eyebrow">COGNITIVE APPRAISAL ANNOTATION</div>
                <h1>从情境出发，理解表达。</h1>
                <p>核对可观察事实，为每一项评价留下依据。</p>
              </div>
              <button
                className="button secondary"
                onClick={() => setGuide(true)}
              >
                <CircleHelp size={16} />
                评分指南
              </button>
            </div>
            <div className="taskbar">
              <div>
                <span className="task-icon">
                  <FileText size={18} />
                </span>
                <strong>{clip}</strong>
                <span className="thin-divider" />
                <span>完整视听</span>
                <span className="pill">模拟情境</span>
              </div>
              <div className="task-navigation">
                <span>
                  {Math.max(1, samples.findIndex((s) => s.clip_id === clip) + 1)
                    .toString()
                    .padStart(3, "0")}{" "}
                  <small>/ 360</small>
                </span>
                <button
                  aria-label="上一个样本"
                  disabled={
                    saving || samples.findIndex((s) => s.clip_id === clip) <= 0
                  }
                  onClick={() =>
                    changeClip(
                      samples[samples.findIndex((s) => s.clip_id === clip) - 1]
                        .clip_id,
                    )
                  }
                >
                  <ChevronLeft size={17} />
                </button>
                <button
                  aria-label="下一个样本"
                  disabled={
                    saving ||
                    samples.findIndex((s) => s.clip_id === clip) >=
                      samples.length - 1
                  }
                  onClick={() =>
                    changeClip(
                      samples[samples.findIndex((s) => s.clip_id === clip) + 1]
                        .clip_id,
                    )
                  }
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </div>
            {!doc || !sample ? (
              <div className="loading">
                <LoaderCircle className="spin" />
                正在载入独立 CPM 工作空间…
              </div>
            ) : (
              <div className="work-grid">
                <section className="media-column">
                  <div className="video-card">
                    <div className="video-topline">
                      <span>
                        <Video size={15} />
                        完整视频
                      </span>
                      <span>DEMO / 12 SEC</span>
                    </div>
                    <div className="video-stage">
                      <video
                        key={clip}
                        ref={video}
                        src="/cpm-api/demo.mp4"
                        poster="/demo-poster.svg"
                        controls
                        preload="metadata"
                        onTimeUpdate={(e) =>
                          setCurrent(e.currentTarget.currentTime)
                        }
                        onError={() => setMediaError(true)}
                      />
                      <span className="video-label">
                        合成视听素材 · 仅演示播放器
                      </span>
                      {mediaError && (
                        <div className="media-error">
                          素材加载失败，请刷新页面重试。
                        </div>
                      )}
                    </div>
                    <div className="video-footer">
                      <span>
                        <Focus size={14} />
                        目标主体：{doc.card.subject}
                      </span>
                      <button
                        className="text-button"
                        onClick={() => {
                          seek(0);
                          void video.current
                            ?.play()
                            .catch(() =>
                              setError(
                                "浏览器暂未允许播放，请使用播放器播放键。",
                              ),
                            );
                        }}
                      >
                        <RotateCcw size={14} />
                        重播
                      </button>
                    </div>
                  </div>
                  <div className="scenario-card">
                    <div className="section-kicker">
                      <span>
                        <FileText size={14} />
                        虚构情境文本
                      </span>
                      <span>不对应合成画面</span>
                    </div>
                    <blockquote>“{sample.original_card.quote}”</blockquote>
                    <p>示意材料用于体验流程；正式样本与媒体稍后接入。</p>
                  </div>
                  <div className="evidence-panel">
                    <div className="panel-heading">
                      <h2>
                        证据工作区{" "}
                        <span>
                          {doc.evidence.filter((e) => e.verified).length}/
                          {doc.evidence.length}
                        </span>
                      </h2>
                      <span className="muted">核对后可引用</span>
                    </div>
                    <p className="panel-description">
                      以下描述来自模拟卡片。正式标注时，核对事实与时间后再勾选。
                    </p>
                    {doc.evidence.map((evidence, index) => (
                      <div
                        className={`evidence-card ${evidence.verified ? "verified" : ""}`}
                        key={evidence.id}
                      >
                        <div className="evidence-top">
                          <span className="evidence-id">{evidence.id}</span>
                          <select
                            aria-label={`${evidence.id}通道`}
                            value={evidence.modality}
                            onChange={(e) =>
                              patch({
                                evidence: doc.evidence.map((item, i) =>
                                  i === index
                                    ? {
                                        ...item,
                                        modality: e.target.value as Channel,
                                      }
                                    : item,
                                ),
                              })
                            }
                          >
                            {Object.entries(channels).map(([id, name]) => (
                              <option key={id} value={id}>
                                {name}
                              </option>
                            ))}
                          </select>
                          <button onClick={() => seek(evidence.span[0])}>
                            <Play size={11} />
                            {evidence.span[0].toFixed(1)}–
                            {evidence.span[1].toFixed(1)}s
                          </button>
                        </div>
                        <textarea
                          aria-label={`${evidence.id}观察描述`}
                          rows={2}
                          value={evidence.observation}
                          onChange={(e) =>
                            patch({
                              evidence: doc.evidence.map((item, i) =>
                                i === index
                                  ? {
                                      ...item,
                                      observation: e.target.value,
                                      verified: false,
                                    }
                                  : item,
                              ),
                            })
                          }
                        />
                        <div className="evidence-bottom">
                          <div className="compact-time">
                            <input
                              aria-label={`${evidence.id}起始时间`}
                              type="number"
                              min={0}
                              max={12}
                              step={0.1}
                              value={evidence.span[0]}
                              onChange={(e) =>
                                patch({
                                  evidence: doc.evidence.map((item, i) =>
                                    i === index
                                      ? {
                                          ...item,
                                          span: [
                                            Number(e.target.value),
                                            item.span[1],
                                          ],
                                          verified: false,
                                        }
                                      : item,
                                  ),
                                })
                              }
                            />
                            <span>—</span>
                            <input
                              aria-label={`${evidence.id}结束时间`}
                              type="number"
                              min={0}
                              max={12}
                              step={0.1}
                              value={evidence.span[1]}
                              onChange={(e) =>
                                patch({
                                  evidence: doc.evidence.map((item, i) =>
                                    i === index
                                      ? {
                                          ...item,
                                          span: [
                                            item.span[0],
                                            Number(e.target.value),
                                          ],
                                          verified: false,
                                        }
                                      : item,
                                  ),
                                })
                              }
                            />
                            <span>s</span>
                          </div>
                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={evidence.verified}
                              onChange={(e) =>
                                patch({
                                  evidence: doc.evidence.map((item, i) =>
                                    i === index
                                      ? { ...item, verified: e.target.checked }
                                      : item,
                                  ),
                                })
                              }
                            />
                            已核对
                          </label>
                        </div>
                      </div>
                    ))}
                    <button
                      className="add-evidence"
                      onClick={() =>
                        patch({
                          evidence: [
                            ...doc.evidence,
                            {
                              id: `E${String(doc.evidence.length + 1).padStart(2, "0")}`,
                              modality: "body",
                              span: [0, sample.duration],
                              observation: "",
                              verified: false,
                            },
                          ],
                        })
                      }
                    >
                      ＋ 添加人工证据
                    </button>
                  </div>
                  <div className="method-note">
                    <ShieldCheck size={17} />
                    <p>
                      先记录观察，再作评价。
                      <span>
                        不显示模型分数、整体情感标签或另一位标注者的答案。
                      </span>
                    </p>
                  </div>
                </section>

                <section className="annotation-column">
                  <div className="steps">
                    {steps.map((label, index) => (
                      <button
                        className={
                          step === index
                            ? "active"
                            : step > index
                              ? "visited"
                              : ""
                        }
                        key={label}
                        onClick={() => goStep(index)}
                      >
                        <span>{index + 1}</span>
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="annotation-content" ref={content}>
                    <div className="section-title">
                      <div>
                        <span className="overline">
                          STEP {String(step + 1).padStart(2, "0")} / 04
                        </span>
                        <h2>
                          {
                            [
                              "看见事实，核对情境",
                              "对事件作出四维评价",
                              "核对表达之间的差异",
                              "记录变化，完成本条标注",
                            ][step]
                          }
                        </h2>
                      </div>
                      <span className="required-note">* 为必填项</span>
                    </div>
                    {step === 0 && (
                      <>
                        <div className="info-callout">
                          <Sparkles size={17} />
                          <div>
                            <strong>这是一张待核对的场景卡</strong>
                            <p>
                              观看素材后，逐项确认或修订。无法判断时选择“信息不足”。
                            </p>
                          </div>
                        </div>
                        {cardFields.map(({ key, label, hint }) => (
                          <div className="field-card" key={key}>
                            <div className="field-heading">
                              <label htmlFor={`card-${key}`}>
                                {label}
                                <b> *</b>
                              </label>
                              <span>
                                {doc.checks[key] === "confirmed" ? (
                                  <>
                                    <Check size={12} />
                                    已核对
                                  </>
                                ) : doc.checks[key] === "unknown" ? (
                                  "信息不足"
                                ) : (
                                  "待核对"
                                )}
                              </span>
                            </div>
                            <input
                              id={`card-${key}`}
                              value={doc.card[key]}
                              placeholder="未提供线索，可选择信息不足"
                              onChange={(e) =>
                                patch({
                                  card: { ...doc.card, [key]: e.target.value },
                                  checks: { ...doc.checks, [key]: "" },
                                })
                              }
                            />
                            <div className="field-actions">
                              <small>{hint}</small>
                              <button
                                className={
                                  doc.checks[key] === "confirmed"
                                    ? "mini-button selected"
                                    : "mini-button"
                                }
                                onClick={() =>
                                  patch({
                                    checks: {
                                      ...doc.checks,
                                      [key]: "confirmed",
                                    },
                                  })
                                }
                              >
                                <Check size={12} />
                                确认
                              </button>
                              {key !== "subject" && (
                                <button
                                  className={
                                    doc.checks[key] === "unknown"
                                      ? "mini-button selected"
                                      : "mini-button"
                                  }
                                  onClick={() =>
                                    patch({
                                      checks: {
                                        ...doc.checks,
                                        [key]: "unknown",
                                      },
                                    })
                                  }
                                >
                                  信息不足
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                        <div className="form-section">
                          <h3>
                            事件时间 <b>*</b>
                          </h3>
                          <Choices
                            value={doc.event_location}
                            options={[
                              ["inside", "发生在片段内"],
                              ["outside", "片段外被明确提及"],
                              ["unknown", "无法定位"],
                            ]}
                            onChange={(value) =>
                              patch({ event_location: value })
                            }
                          />
                          {doc.event_location === "inside" && (
                            <WindowInput
                              value={doc.event_window}
                              duration={sample.duration}
                              current={current}
                              onChange={(value) =>
                                patch({ event_window: value })
                              }
                            />
                          )}
                        </div>
                        <div className="form-section">
                          <h3>
                            当前评分区间 <b>*</b>
                          </h3>
                          <p>本次 R / I / C / N 评分适用的媒体时间范围。</p>
                          <WindowInput
                            value={doc.score_window}
                            duration={sample.duration}
                            current={current}
                            onChange={(value) => patch({ score_window: value })}
                          />
                        </div>
                      </>
                    )}
                    {step === 1 && (
                      <>
                        <div className="info-callout compact">
                          <CircleHelp size={17} />
                          <p>
                            评分无默认值。0
                            表示已判断的中间状态，“信息不足”独立保存。四维分数不求和。
                          </p>
                        </div>
                        <RatingFields
                          ratings={doc.ratings}
                          evidence={doc.evidence}
                          onChange={(ratings) => patch({ ratings })}
                        />
                      </>
                    )}
                    {step === 2 && (
                      <>
                        <div className="candidate-window">
                          <div>
                            <span className="overline">
                              候选窗口 · 模拟来源
                            </span>
                            <h3>
                              02.4 — 04.8 <small>秒</small>
                            </h3>
                            <p>辅助定位，不代表已确认冲突。</p>
                          </div>
                          <button
                            className="button secondary"
                            onClick={() => seek(2.4)}
                          >
                            <Play size={14} />
                            定位窗口
                          </button>
                        </div>
                        <div className="form-section">
                          <h3>
                            冲突核对结论 <b>*</b>
                          </h3>
                          <Choices
                            value={doc.conflict.status}
                            options={[
                              ["confirmed", "明确冲突"],
                              ["not_confirmed", "未确认冲突"],
                              ["uncertain", "不确定"],
                            ]}
                            onChange={(status) =>
                              patch({ conflict: { ...doc.conflict, status } })
                            }
                          />
                        </div>
                        {doc.conflict.status === "confirmed" && (
                          <>
                            <div className="form-section">
                              <h3>
                                人工核对区间 <b>*</b>
                              </h3>
                              <WindowInput
                                value={doc.conflict.reviewed_window}
                                duration={sample.duration}
                                current={current}
                                onChange={(value) =>
                                  patch({
                                    conflict: {
                                      ...doc.conflict,
                                      reviewed_window: value,
                                    },
                                  })
                                }
                              />
                              <p>原始候选窗口会保留，人工调整单独保存。</p>
                            </div>
                            <div className="form-section">
                              <h3>
                                涉及通道 <b>*</b>
                              </h3>
                              <ChannelChoices
                                values={doc.conflict.modalities}
                                onChange={(modalities) =>
                                  patch({
                                    conflict: { ...doc.conflict, modalities },
                                  })
                                }
                              />
                              <p>
                                至少两个通道，每个通道都需要左侧已核对的时间证据。
                              </p>
                            </div>
                          </>
                        )}
                        <div className="form-section">
                          <h3>
                            语境整合说明 <span className="optional">可选</span>
                          </h3>
                          <textarea
                            rows={3}
                            placeholder="若整合语境后可以协调解释，在此保留判断。"
                            value={doc.conflict.reconciliation}
                            onChange={(e) =>
                              patch({
                                conflict: {
                                  ...doc.conflict,
                                  reconciliation: e.target.value,
                                },
                              })
                            }
                          />
                        </div>
                        <div className="form-section">
                          <h3>
                            规范或角色对表达的约束 <b>*</b>
                          </h3>
                          <p>与 N 的事件规范评价分开，例如“需要尊重对手”。</p>
                          <Choices
                            value={doc.constraint.status}
                            options={[
                              ["present", "有明确线索"],
                              ["absent", "未见明确线索"],
                              ["unknown", "信息不足"],
                            ]}
                            onChange={(status) =>
                              patch({
                                constraint: { ...doc.constraint, status },
                              })
                            }
                          />
                          {doc.constraint.status === "present" && (
                            <>
                              <div className="rating-evidence">
                                {doc.evidence
                                  .filter((e) => e.verified)
                                  .map((e) => (
                                    <label key={e.id}>
                                      <input
                                        type="checkbox"
                                        checked={doc.constraint.evidence_ids.includes(
                                          e.id,
                                        )}
                                        onChange={(event) =>
                                          patch({
                                            constraint: {
                                              ...doc.constraint,
                                              evidence_ids: event.target.checked
                                                ? [
                                                    ...doc.constraint
                                                      .evidence_ids,
                                                    e.id,
                                                  ]
                                                : doc.constraint.evidence_ids.filter(
                                                    (id) => id !== e.id,
                                                  ),
                                            },
                                          })
                                        }
                                      />
                                      {e.id} · {channels[e.modality]}
                                    </label>
                                  ))}
                              </div>
                              <textarea
                                rows={2}
                                placeholder="补充表达约束线索（可选）"
                                value={doc.constraint.note}
                                onChange={(e) =>
                                  patch({
                                    constraint: {
                                      ...doc.constraint,
                                      note: e.target.value,
                                    },
                                  })
                                }
                              />
                            </>
                          )}
                        </div>
                      </>
                    )}
                    {step === 3 && (
                      <>
                        <div className="form-section">
                          <h3>
                            表达是否有可观察变化 <b>*</b>
                          </h3>
                          <Choices
                            value={doc.dynamic.status}
                            options={[
                              ["changed", "有明确变化"],
                              ["unchanged", "未见明确变化"],
                              ["unknown", "信息不足"],
                            ]}
                            onChange={(status) =>
                              patch({ dynamic: { ...doc.dynamic, status } })
                            }
                          />
                        </div>
                        {doc.dynamic.status === "changed" && (
                          <>
                            <div className="form-section">
                              <h3>
                                变化时间与通道 <b>*</b>
                              </h3>
                              <div className="window-input">
                                <label>
                                  时间{" "}
                                  <input
                                    type="number"
                                    aria-label="变化时间"
                                    min={0}
                                    max={sample.duration}
                                    step={0.1}
                                    value={doc.dynamic.time}
                                    onChange={(e) =>
                                      patch({
                                        dynamic: {
                                          ...doc.dynamic,
                                          time: Number(e.target.value),
                                        },
                                      })
                                    }
                                  />
                                  s
                                </label>
                                <button
                                  className="text-button"
                                  onClick={() =>
                                    patch({
                                      dynamic: {
                                        ...doc.dynamic,
                                        time: Number(current.toFixed(2)),
                                      },
                                    })
                                  }
                                >
                                  使用播放器当前时间
                                </button>
                              </div>
                              <ChannelChoices
                                values={doc.dynamic.modalities}
                                onChange={(modalities) =>
                                  patch({
                                    dynamic: { ...doc.dynamic, modalities },
                                  })
                                }
                              />
                              <textarea
                                rows={3}
                                placeholder="描述观察到的变化，不将通道顺序命名为内部 appraisal 阶段"
                                value={doc.dynamic.description}
                                onChange={(e) =>
                                  patch({
                                    dynamic: {
                                      ...doc.dynamic,
                                      description: e.target.value,
                                    },
                                  })
                                }
                              />
                            </div>
                            <label className="check-label">
                              <input
                                type="checkbox"
                                checked={doc.dynamic.updated_ratings !== null}
                                onChange={(e) =>
                                  patch({
                                    dynamic: {
                                      ...doc.dynamic,
                                      updated_ratings: e.target.checked
                                        ? blankRatings()
                                        : null,
                                    },
                                  })
                                }
                              />
                              事件评价本身有可支持的变化，增加一组评分
                            </label>
                            {doc.dynamic.updated_ratings && (
                              <>
                                <div className="form-section">
                                  <h3>变化后评分区间</h3>
                                  <WindowInput
                                    value={doc.dynamic.score_window}
                                    duration={sample.duration}
                                    onChange={(score_window) =>
                                      patch({
                                        dynamic: {
                                          ...doc.dynamic,
                                          score_window,
                                        },
                                      })
                                    }
                                  />
                                </div>
                                <RatingFields
                                  ratings={doc.dynamic.updated_ratings}
                                  evidence={doc.evidence}
                                  onChange={(updated_ratings) =>
                                    patch({
                                      dynamic: {
                                        ...doc.dynamic,
                                        updated_ratings,
                                      },
                                    })
                                  }
                                />
                              </>
                            )}
                          </>
                        )}
                        <div className="submission-summary">
                          <h3>
                            <ListChecks size={18} />
                            提交摘要
                          </h3>
                          <div>
                            <span>目标主体</span>
                            <strong>{doc.card.subject || "未填写"}</strong>
                          </div>
                          <div>
                            <span>评分适用区间</span>
                            <strong>{doc.score_window.join(" — ")} s</strong>
                          </div>
                          <div>
                            <span>已核对证据</span>
                            <strong>
                              {doc.evidence.filter((e) => e.verified).length} 条
                            </strong>
                          </div>
                          <div className="summary-ratings">
                            {dimensions.map((d) => (
                              <span key={d.id}>
                                {d.id}
                                <strong>
                                  {doc.ratings[d.id].state === "unknown"
                                    ? "未知"
                                    : doc.ratings[d.id].state === "unset"
                                      ? "待填"
                                      : doc.ratings[d.id].value}
                                </strong>
                              </span>
                            ))}
                          </div>
                          <p>提交时将检查必填项、时间区间和依据引用。</p>
                        </div>
                        <div className="form-section">
                          <h3>
                            修订原因{" "}
                            <span className="optional">
                              修改已提交记录时必填
                            </span>
                          </h3>
                          <textarea
                            rows={2}
                            value={doc.revision_reason}
                            placeholder="首次提交可留空；修订会保留原始记录。"
                            onChange={(e) =>
                              patch({ revision_reason: e.target.value })
                            }
                          />
                        </div>
                        <div className="info-callout compact">
                          <LockKeyhole size={17} />
                          <p>
                            本次答案独立保存至 {annotator}
                            。原卡片、候选窗口与全部保存版本均保留。
                          </p>
                        </div>
                      </>
                    )}
                    <div className="section-bottom">
                      <span>候选量表 v1 · 尚未冻结</span>
                      <span>CPM / XMER</span>
                    </div>
                  </div>
                  <footer className="annotation-footer">
                    <div className="save-state">
                      {dirty ? (
                        <span className="unsaved-dot" />
                      ) : (
                        <CheckCheck size={16} />
                      )}
                      <span>{saveMessage}</span>
                    </div>
                    <div>
                      <button
                        className="button secondary"
                        disabled={saving}
                        onClick={() => save("draft")}
                      >
                        {saving ? (
                          <LoaderCircle size={15} className="spin" />
                        ) : (
                          <Save size={15} />
                        )}
                        保存草稿
                      </button>
                      {step > 0 && (
                        <button
                          className="icon-button"
                          aria-label="上一步"
                          onClick={() => goStep(step - 1)}
                        >
                          <ArrowLeft size={17} />
                        </button>
                      )}
                      <button
                        className="button primary"
                        disabled={saving}
                        onClick={() =>
                          step < 3 ? goStep(step + 1) : save("submitted")
                        }
                      >
                        {step < 3 ? "下一步" : "提交标注"}
                        {step < 3 ? (
                          <ArrowRight size={16} />
                        ) : (
                          <Check size={16} />
                        )}
                      </button>
                    </div>
                  </footer>
                </section>
              </div>
            )}
          </>
        ) : (
          <div className="admin-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">DATASET & ANNOTATION MANAGEMENT</div>
                <h1>样本与数据管理</h1>
                <p>同一批样本，两份独立评价。保留证据、版本与分歧。</p>
              </div>
              <button className="button primary" onClick={exportData}>
                <ArrowDownToLine size={16} />
                导出数据
              </button>
            </div>
            <div className="admin-stats">
              <div>
                <span>子集样本</span>
                <strong>
                  360 <small>条</small>
                </strong>
                <p>CPM-DEMO-360 · 模拟数据</p>
              </div>
              <div>
                <span>标注任务</span>
                <strong>
                  720 <small>条</small>
                </strong>
                <p>每人 360 条 · 完全相同的子集</p>
              </div>
              <div>
                <span>已提交标注</span>
                <strong>
                  {admin?.counts.reduce((sum, c) => sum + c.submitted, 0) ?? 0}{" "}
                  <small>/ 720</small>
                </strong>
                <p>以每项任务的最新保存版本为准</p>
              </div>
              <div>
                <span>样本来源</span>
                <strong className="source-stat">模拟子集</strong>
                <p>预留 VA 样本编号与筛选元数据</p>
              </div>
            </div>
            <div className="admin-two-col">
              <section className="admin-card">
                <h2>
                  标注者进度 <span>独立全量</span>
                </h2>
                {admin?.counts.map((c) => (
                  <div key={c.annotator} className="annotator-progress">
                    <div className="avatar">{c.annotator.slice(-2)}</div>
                    <div>
                      <strong>{c.annotator}</strong>
                      <div className="progress-track">
                        <i
                          style={{ width: `${(c.submitted / c.total) * 100}%` }}
                        />
                      </div>
                    </div>
                    <span>
                      {c.submitted} / {c.total}
                      <small>{c.draft} 条草稿</small>
                    </span>
                  </div>
                ))}
              </section>
              <section className="admin-card source-card">
                <div className="source-icon">
                  <Layers3 size={22} />
                </div>
                <div>
                  <h2>为后续 VA 筛选保留入口</h2>
                  <p>
                    每个样本保留 <code>va_clip_id</code>{" "}
                    与筛选来源元数据。当前为空，待子集确定后接入真实清单。
                  </p>
                  <span className="pill">当前仅使用模拟数据</span>
                </div>
              </section>
            </div>
            <section className="admin-card samples-table">
              <div className="panel-heading">
                <h2>
                  样本清单 <span>{filtered.length}</span>
                </h2>
                <span className="muted">
                  当前查看 {annotator} · 使用左侧搜索与筛选
                </span>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>样本编号</th>
                    <th>情境摘要</th>
                    <th>来源</th>
                    <th>VA 关联</th>
                    <th>当前状态</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filtered
                    .slice(adminPage * 12, adminPage * 12 + 12)
                    .map((s) => (
                      <tr key={s.clip_id}>
                        <td className="mono">{s.clip_id}</td>
                        <td>{s.original_card.event}</td>
                        <td>
                          <span className="pill">模拟</span>
                        </td>
                        <td className="muted">待确定</td>
                        <td>
                          <span
                            className={`status-badge ${s.status || "todo"}`}
                          >
                            {s.status === "submitted"
                              ? "已提交"
                              : s.status === "draft"
                                ? "草稿"
                                : "待标注"}
                          </span>
                        </td>
                        <td>
                          <button
                            className="text-button"
                            onClick={() => {
                              changeClip(s.clip_id);
                              setPage("work");
                            }}
                          >
                            打开
                            <ArrowRight size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <div className="table-pagination">
                <span>
                  第 {adminPage + 1} /{" "}
                  {Math.max(1, Math.ceil(filtered.length / 12))} 页
                </span>
                <button
                  disabled={adminPage === 0}
                  onClick={() => setAdminPage((p) => p - 1)}
                >
                  <ChevronLeft size={17} />
                </button>
                <button
                  disabled={(adminPage + 1) * 12 >= filtered.length}
                  onClick={() => setAdminPage((p) => p + 1)}
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </section>
            <section className="admin-card">
              <h2>保存与修订记录</h2>
              {!admin?.recent.length ? (
                <p className="empty-state">
                  尚无保存记录。完成第一份草稿后，会在这里看到可追踪的版本。
                </p>
              ) : (
                <div className="audit-list">
                  {admin.recent.map((record) => (
                    <div key={record.id}>
                      <span className="mono">{record.task_id}</span>
                      <span>版本 {record.attempt_no}</span>
                      <span>
                        {record.status === "submitted" ? "提交" : "草稿"}
                      </span>
                      <time>
                        {new Date(record.created_at).toLocaleString("zh-CN")}
                      </time>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </main>
      {guide && (
        <div className="modal-backdrop" onClick={() => setGuide(false)}>
          <section
            className="guide-modal"
            role="dialog"
            aria-modal="true"
            aria-label="CPM 标注指南"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close-modal"
              aria-label="关闭指南"
              onClick={() => setGuide(false)}
            >
              <X size={20} />
            </button>
            <div className="eyebrow">ANNOTATION GUIDE</div>
            <h2>让每个评价，都有据可查。</h2>
            <p>本页使用 2026-10-05 候选量表。真实试标前仍需冻结定义与培训。</p>
            {dimensions.map((d) => (
              <div className="guide-dimension" key={d.id}>
                <span className={`dimension dimension-${d.id}`}>{d.id}</span>
                <div>
                  <h3>{d.name}</h3>
                  <p>{d.question}</p>
                  <small>{d.hint}</small>
                </div>
              </div>
            ))}
            <div className="info-callout">
              <CircleHelp size={18} />
              <p>
                0 ≠
                信息不足；评分不相加；冲突至少需要两个通道的时间证据。表达变化不等同于内部评价阶段。
              </p>
            </div>
            <p className="muted">
              演示账号切换仅供本机预览。当前未配置正式账号认证；尚未接入 LLM
              扩写与审核。
            </p>
            <button className="button primary" onClick={() => setGuide(false)}>
              开始核对
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
