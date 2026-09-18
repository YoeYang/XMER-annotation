import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, CornerDownLeft, RotateCcw } from "lucide-react";
import { AnnotationSession } from "../core/session";
import { dimensionSubmitted, latestAttempt } from "../core/taskFlow";
import type { AnnotationRepository } from "../storage/repository";
import type { SyncState } from "../storage/syncingRepository";
import type { Attempt, Dimension, FlowPage, Submission, Task } from "../types";
import { useLang } from "../LangContext";
import type { Key } from "../i18n";
import AnnotationPad from "./AnnotationPad";
import TraceChart from "./TraceChart";
import MediaPanel from "./MediaPanel";

interface Props {
  task: Task;
  sync: SyncState | null;
  position: number;
  sectionTotal: number;
  annotator: string;
  repository: AnnotationRepository;
  attempts: Attempt[];
  submissions: Submission[];
  refresh: () => Promise<void>;
  register: (session: AnnotationSession | null) => void;
  onNext: () => void;
  onReload: () => void;
  onGuide: () => void;
}

export default function Workspace(props: Props) {
  const { task, annotator, repository } = props;
  const taskAttempts = useMemo(
    () => props.attempts.filter((attempt) => attempt.task_id === task.task_id),
    [props.attempts, task.task_id],
  );
  const taskSubmissions = useMemo(
    () =>
      props.submissions.filter(
        (submission) => submission.task_id === task.task_id,
      ),
    [props.submissions, task.task_id],
  );
  const valenceSubmitted = dimensionSubmitted(
    taskAttempts,
    taskSubmissions,
    task.task_id,
    "valence",
  );
  const arousalSubmitted = dimensionSubmitted(
    taskAttempts,
    taskSubmissions,
    task.task_id,
    "arousal",
  );
  const initialPage: FlowPage = valenceSubmitted
    ? "arousal"
    : latestAttempt(taskAttempts, task.task_id, "valence")
      ? "valence"
      : "familiarization";
  const initialPlays = taskAttempts.at(-1)?.familiarization_plays ?? 0;
  const [session] = useState(
    () => new AnnotationSession(task, annotator, repository),
  );
  const [view, setView] = useState(session.view);
  const [page, setPage] = useState<FlowPage>(initialPage);
  const [familiarizationPlays, setFamiliarizationPlays] =
    useState(initialPlays);
  const [reannotating, setReannotating] = useState(false);
  const [busy, setBusy] = useState(false);
  const { t } = useLang();
  const [notice, setNotice] = useState("");

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
    if (initialPage !== "familiarization")
      void session.prepareDimension(initialPage, initialPlays);
  }, []);

  useEffect(() => {
    if (view.savedAt)
      void props.refresh().catch((error) => setNotice(String(error)));
  }, [view.savedAt]);

  const run = async (operation: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      await operation();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : t("err.retry"));
    } finally {
      setBusy(false);
    }
  };

  const dimension = page === "familiarization" ? null : page;
  const storedAttempt = dimension
    ? latestAttempt(taskAttempts, task.task_id, dimension)
    : undefined;
  const current =
    view.attempt?.dimension === dimension ? view.attempt : storedAttempt;
  const submitted =
    dimension === "valence"
      ? valenceSubmitted
      : dimension === "arousal"
        ? arousalSubmitted
        : false;
  const activeAttempt =
    view.attempt?.dimension === dimension &&
    ["recording", "paused"].includes(view.attempt.status);
  const hasExisting = !!storedAttempt || submitted || !!view.attempt;
  const canAnnotate =
    !!dimension &&
    !busy &&
    (activeAttempt || reannotating || (!storedAttempt && !submitted)) &&
    view.phase !== "completed";
  const canRestart =
    !!dimension &&
    hasExisting &&
    !["loading", "starting", "recording", "hold-delay", "buffering"].includes(
      view.phase,
    );
  const canAdvance =
    page === "familiarization" ||
    (!reannotating && submitted) ||
    ((reannotating ? view.attempt : current)?.status === "completed" &&
      (reannotating ? view.attempt : current)!.sample_count > 0);

  const goToDimension = async (next: Dimension) => {
    setPage(next);
    setReannotating(false);
    await session.prepareDimension(next, familiarizationPlays);
  };

  const next = useCallback(() => {
    if (busy || !canAdvance) return;
    void run(async () => {
      if (page === "familiarization") {
        const plays = await session.finishFamiliarization();
        setFamiliarizationPlays(plays);
        setPage("valence");
        setReannotating(false);
        await session.prepareDimension("valence", plays);
        return;
      }
      if (
        current &&
        !taskSubmissions.some(
          (submission) => submission.attempt_id === current.attempt_id,
        )
      ) {
        await session.flush();
        // 只等本机落库（毫秒级），上传交给后台——等一次网络往返会让
        // 「下一步」明显卡一下，标一条卡一次。上传进度由云端状态条显示，
        // 侧栏的勾靠本机与云端的并集列表，都不必挡着人往下走。
        await repository.submit(current.attempt_id);
        void props.refresh();
      }
      if (page === "valence") {
        await goToDimension("arousal");
      } else {
        props.onNext();
      }
    });
  }, [
    busy,
    canAdvance,
    page,
    current?.attempt_id,
    taskSubmissions,
    familiarizationPlays,
  ]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== "Enter" ||
        event.repeat ||
        event.isComposing ||
        document.querySelector('[aria-modal="true"]') ||
        ["SELECT", "INPUT", "TEXTAREA"].includes(
          (event.target as HTMLElement | null)?.tagName ?? "",
        )
      )
        return;
      event.preventDefault();
      next();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [next]);

  const back = () =>
    void run(async () => {
      if (page === "arousal") {
        await goToDimension("valence");
        return;
      }
      if (page === "valence") {
        await session.leave();
        setPage("familiarization");
        setReannotating(false);
      }
    });

  const restart = () =>
    void run(async () => {
      await session.resetDimension();
      setReannotating(true);
    });

  return (
    <main className="workspace v3-workspace">
      <div className="workspace-heading">
        <h1>
          {t(("modality." + task.modality) as Key)} {props.position}/{props.sectionTotal}
        </h1>
      </div>

      <div className="annotation-grid">
        <div className="media-column">
          <MediaPanel
            key={task.task_id}
            task={task}
            page={page}
            session={session}
            view={view}
            onReload={props.onReload}
          />
          {/* 标注者按住拖动时只感觉得到手往哪边挪，看不到画出了什么形状；
              这条线让人对自己的判断有个整体印象。熟悉页没有轨迹可言。 */}
          {page !== "familiarization" && (
            <TraceChart
              trace={view.trace}
              duration={view.duration || task.duration}
              time={view.time}
              dimension={view.dimension}
            />
          )}
        </div>
        <div className="annotation-column">
          <AnnotationPad
            page={page}
            view={view}
            canAnnotate={canAnnotate}
            onPress={(value) => session.press(value)}
            onMove={(value) => session.setValue(value)}
            onRelease={() => session.releaseHold()}
            onGuide={() => {
              if (dimension) session.releaseHold();
              props.onGuide();
            }}
          />

          {/* 不显示保存/上传状态：那分散注意力，而标注者对它也无能为力。
              侧栏打勾即代表这条标完并已记下，上传是否到云端在管理后台看。
              只有本机都写不进去（浏览器存储被禁/满）才必须告诉人，
              那种情况下继续标就是白标。 */}
          {(notice || view.save === "error") && (
            <p className="operation-notice" role="status">
              {notice ||
                t("err.localStorage") + "：" + view.saveError}
            </p>
          )}

          <div className="v3-navigation">
            <button
              className="back-step"
              disabled={page === "familiarization" || busy}
              onClick={back}
            >
              <ArrowLeft size={17} />
              {t("step.back")}
            </button>
            <button
              className="restart-dimension"
              aria-label={t("step.redo")}
              title={t("step.redoHint")}
              disabled={!canRestart || busy}
              onClick={restart}
            >
              <RotateCcw size={16} />
              {t("step.redo")}
            </button>
            <button
              className="next-step"
              disabled={!canAdvance || busy}
              onClick={next}
            >
              <span>
                {page === "familiarization" ? t("step.gotIt") : t("step.next")}
              </span>
              <kbd>
                <CornerDownLeft size={16} />
                回车
              </kbd>
              <ArrowRight size={20} />
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
