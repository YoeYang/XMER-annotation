import { useEffect, useState } from "react";
import { ArrowRight, Info, Save } from "lucide-react";
import { AnnotationSession } from "../core/session";
import type { AnnotationRepository } from "../storage/repository";
import type { Attempt, Submission, Task } from "../types";
import { formatDate, MODALITY_LABELS, SAMPLE_RATE_HZ } from "../config";
import AnnotationPad from "./AnnotationPad";
import MediaPanel from "./MediaPanel";
import AttemptPanel from "./AttemptPanel";
interface Props {
  task: Task;
  index: number;
  total: number;
  annotator: string;
  repository: AnnotationRepository;
  attempts: Attempt[];
  submissions: Submission[];
  refresh: () => Promise<void>;
  register: (session: AnnotationSession | null) => void;
  onNext: () => void;
  onReload: () => void;
  onExport: () => Promise<void>;
}
export default function Workspace(props: Props) {
  const { task, annotator, repository } = props;
  const [session] = useState(
    () => new AnnotationSession(task, annotator, repository),
  );
  const [view, setView] = useState(session.view),
    [selected, setSelected] = useState(""),
    [preparingNew, setPreparingNew] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const attempts = props.attempts.filter((a) => a.task_id === task.task_id),
    submissions = props.submissions.filter((s) => s.task_id === task.task_id);
  const current = preparingNew
    ? null
    : selected
      ? (attempts.find((a) => a.attempt_id === selected) ?? null)
      : view.attempt?.mode === "annotation"
        ? view.attempt
        : (attempts.filter((a) => a.mode === "annotation").at(-1) ?? null);
  useEffect(() => {
    props.register(session);
    const unsubscribe = session.subscribe(() => setView(session.view));
    return () => {
      unsubscribe();
      session.dispose();
      props.register(null);
    };
  }, [session]);
  useEffect(() => {
    if (view.savedAt)
      void props.refresh().catch((error) => setNotice(String(error)));
  }, [view.savedAt]);
  const action = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      await fn();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="workspace">
      <div className="breadcrumb">
        标注工作台 <span>/</span> 样本{" "}
        {String(props.index + 1).padStart(2, "0")}
      </div>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">CONTINUOUS EMOTION ANNOTATION</div>
          <h1>{task.title}</h1>
          <p>
            <span>{task.task_id}</span>
            <i />
            {MODALITY_LABELS[task.modality]}
            <i />
            {task.demo ? "演示任务 · 非实验素材" : task.source_id}
          </p>
        </div>
        <div className="sample-counter">
          <strong>{String(props.index + 1).padStart(2, "0")}</strong>
          <span>/ {String(props.total).padStart(2, "0")}</span>
        </div>
      </div>
      <div className="instruction-strip">
        <Info size={17} />
        <span>
          先熟悉材料，再点击右侧方形开始标注。请判断
          <strong>目标人物的情绪</strong>，而非自己的感受。
        </span>
        <span className="sampling-badge">{SAMPLE_RATE_HZ} Hz 连续采样</span>
      </div>
      <div className="annotation-grid">
        <MediaPanel
          task={task}
          session={session}
          view={view}
          onReload={props.onReload}
        />
        <AnnotationPad
          view={view}
          onMove={(point) => session.setPoint(point)}
          onStart={(point) => {
            setSelected("");
            setPreparingNew(false);
            setNotice("");
            void session.start("annotation", point);
          }}
        />
      </div>
      <div
        className={"save-line " + (view.save === "error" ? "error-text" : "")}
        role="status"
      >
        <Save size={14} />
        <span>
          {view.save === "saving"
            ? "正在保存到本地…"
            : view.save === "saved"
              ? "已保存到本地 · " + formatDate(view.savedAt)
              : view.save === "error"
                ? "保存失败：" + view.saveError
                : "本地自动保存已就绪"}
        </span>
        {view.save === "error" && (
          <button onClick={() => void action(() => session.flush())}>
            重试保存
          </button>
        )}
        <small>仅当前浏览器可读取</small>
      </div>
      <AttemptPanel
        attempts={attempts}
        current={current}
        submissions={submissions}
        view={view}
        selected={selected}
        onSelect={(value) => {
          setPreparingNew(false);
          setSelected(value);
        }}
        busy={busy}
        onSubmit={() =>
          void action(async () => {
            if (!current) return;
            await session.flush();
            const result = await repository.submit(current.attempt_id);
            await props.refresh();
            setNotice(
              result.revision === 1
                ? "Submit 成功，结果已保存到本地。"
                : "Update 成功，历史原始记录已保留。",
            );
          })
        }
        onReset={() =>
          void action(async () => {
            await session.reset();
            setSelected("");
            setPreparingNew(true);
            await props.refresh();
          })
        }
        onExport={() => void action(props.onExport)}
      />
      {notice && (
        <p className="operation-notice" role="status">
          {notice}
        </p>
      )}
      <div className="workspace-footer">
        <span>原始记录始终保留 · 重新标注会创建独立轮次</span>
        <button
          disabled={
            busy ||
            [
              "starting",
              "recording",
              "preview",
              "paused",
              "buffering",
            ].includes(view.phase) ||
            props.index === props.total - 1
          }
          onClick={props.onNext}
        >
          下一个样本 <ArrowRight size={16} />
        </button>
      </div>
    </main>
  );
}
