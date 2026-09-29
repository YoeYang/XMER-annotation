import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  CornerDownLeft,
  GraduationCap,
  MousePointer,
  MousePointerClick,
} from "lucide-react";
import { IndexedDbRepository } from "./storage/indexedDbRepository";
import { HttpRepository } from "./storage/httpRepository";
import { SyncingRepository } from "./storage/syncingRepository";
import type { SyncState } from "./storage/syncingRepository";
import { captureToken, getToken } from "./auth";
import { validateTasks } from "./core/textTimeline";
import {
  allComplete,
  completeModalities,
  completedCount,
  locationOf,
  orderedTasks,
} from "./core/taskFlow";
import { API_BASE } from "./config";
import LangSwitch from "./components/LangSwitch";
import { useLang } from "./LangContext";
import type { Key } from "./i18n";
import type { AnnotationSession } from "./core/session";
import type { Attempt, Modality, Submission, Task } from "./types";
import AllDone from "./components/AllDone";
import Debrief from "./components/Debrief";
import GuideBook from "./components/GuideBook";
import TaskSidebar from "./components/TaskSidebar";
import Workspace from "./components/Workspace";

// 管理员镜像号看的是训练页还是正式页。只有镜像号会用到，普通账号服务端忽略这个参数。
const MIRROR_VIEW_KEY = "xmer-mirror-view";

function switchMirrorView(view: "training" | "main") {
  try {
    localStorage.setItem(MIRROR_VIEW_KEY, view);
  } catch {
    /* 存不下就只切这一次 */
  }
  // 整页重载而不是就地换队列：任务、轮次、提交全都跟着阶段走，就地换容易留下上一批的状态
  const url = new URL(location.href);
  url.searchParams.set("view", view);
  location.href = url.toString();
}

function remembered(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

export default function App() {
  const { t } = useLang();
  const [token] = useState(() => captureToken());
  const [repository] = useState(
    () =>
      new SyncingRepository(
        new IndexedDbRepository(),
        new HttpRepository({ baseUrl: API_BASE, getToken }),
      ),
  );
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState(remembered("xmer-task", ""));
  const [annotator, setAnnotator] = useState("");
  const [profile, setProfile] = useState<{
    name: string;
    phase: string;
    // 训练过、正式阶段可以回看复盘的模态
    trainedModalities: Modality[];
    // 管理员镜像号：可在训练页与正式页之间切换
    mirror: boolean;
  } | null>(null);
  // 正式阶段的「训练回顾」：先选模态，再打开那一段的复盘
  const [pickingReview, setPickingReview] = useState(false);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [locked, setLocked] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [reload, setReload] = useState(0);
  const [pendingTask, setPendingTask] = useState<Task | null>(null);
  const [sync, setSync] = useState<SyncState | null>(null);
  // 全部标完时盖上收尾页。可以关掉回来复查，所以是一个独立的开关而不是
  // 直接拿 allDone 当渲染条件——否则标完就再也打不开任何一条了。
  const [celebrating, setCelebrating] = useState(false);
  // 指南页。训练账号第一次进来自动打开一次，之后靠顶栏的按钮。
  // 「看过了」按账号记——换人用同一台机器时，新来的人还得看一遍。
  const [book, setBook] = useState(false);
  // 正在回看哪一段的曲线对照
  const [reviewing, setReviewing] = useState<Modality | null>(null);
  const activeSession = useRef<AnnotationSession | null>(null);

  const refresh = useCallback(async () => {
    const [nextAttempts, nextSubmissions] = await Promise.all([
      repository.listAttempts(annotator),
      repository.listSubmissions(annotator),
    ]);
    setAttempts(nextAttempts);
    setSubmissions(nextSubmissions);
  }, [repository, annotator]);

  useEffect(() => {
    setSync(repository.getState());
    // 上传队列排空时重新读一次：侧栏的勾只认服务器确认收到的提交，
    // 而提交是不等上传就返回的（等一次网络往返会让「下一步」卡住）。
    // 没有这一下，勾要等到下次手动触发刷新才会出现。
    let pending = repository.getState().pending;
    return repository.subscribe((state) => {
      setSync(state);
      const settled = pending > 0 && state.pending === 0;
      pending = state.pending;
      if (settled && annotator) void refresh();
    }) as unknown as () => void;
  }, [repository, annotator, refresh]);

  useEffect(() => {
    let release: (() => void) | undefined;
    let cancelled = false;
    if (!navigator.locks) {
      setError(
        t("err.needSecure"),
      );
      return;
    }
    void navigator.locks
      .request("xmer-local-editor", { ifAvailable: true }, async (lock) => {
        if (cancelled) return;
        if (!lock) {
          setError(t("err.otherTab"));
          return;
        }
        setLocked(true);
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      })
      .catch((reason) => setError(String(reason)));
    return () => {
      cancelled = true;
      release?.();
    };
  }, []);

  useEffect(() => {
    if (!locked) return;
    if (!token) {
      setError(
        t("err.noToken"),
      );
      return;
    }
    let cancelled = false;
    setReady(false);
    void (async () => {
      try {
        const view =
          new URL(location.href).searchParams.get("view") ??
          remembered(MIRROR_VIEW_KEY, "");
        const response = await fetch(
          API_BASE + "/me" + (view ? "?view=" + encodeURIComponent(view) : ""),
          { headers: { authorization: "Bearer " + token } },
        );
        if (response.status === 401 || response.status === 403)
          throw new Error(t("err.badToken"));
        if (!response.ok) throw new Error(t("err.offline"));
        const me = await response.json();
        if (cancelled) return;
        setAnnotator(me.annotator_id);
        setProfile({
          name: me.display_name || me.annotator_id,
          phase: me.phase,
          trainedModalities: me.training_modalities ?? [],
          mirror: Boolean(me.mirror),
        });
        if (!me.tasks.length) {
          setTasks([]);
          setReady(true);
          return;
        }
        const list = orderedTasks(validateTasks(me.tasks));
        await repository.recoverInterrupted(me.annotator_id);
        // 补发上次卡在本机没送出去的提交。失败了不拦着人干活——
        // 数据还在本机，下次登录再补；拦在这里只会让人连页面都进不去。
        await repository.resyncSubmitted(me.annotator_id).catch(() => 0);
        const [nextAttempts, nextSubmissions] = await Promise.all([
          repository.listAttempts(me.annotator_id),
          repository.listSubmissions(me.annotator_id),
        ]);
        if (cancelled) return;
        setTasks(list);
        const initialTask =
          list.find((task) => task.task_id === selected) ?? list[0];
        setSelected(initialTask.task_id);
        setPendingTask(initialTask);
        setAttempts(nextAttempts);
        setSubmissions(nextSubmissions);
        setReady(true);
      } catch (reason) {
        if (!cancelled)
          setError(
            reason instanceof Error ? reason.message : t("err.workspace"),
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [locked, token, repository]);

  const remember = (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      setError(t("err.rememberTask"));
    }
  };

  const performSelect = async (task: Task) => {
    if (switching || task.task_id === selected) return;
    setSwitching(true);
    try {
      await activeSession.current?.leave();
      setSelected(task.task_id);
      remember("xmer-task", task.task_id);
    } catch {
      setError(t("err.saveRound"));
    } finally {
      setSwitching(false);
    }
  };

  const requestSelect = (task: Task) => {
    const current = tasks.find((row) => row.task_id === selected);
    if (current && current.modality !== task.modality) {
      setPendingTask(task);
      return;
    }
    void performSelect(task);
  };

  useEffect(() => {
    if (!pendingTask) return;
    const confirm = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || event.repeat) return;
      event.preventDefault();
      const task = pendingTask;
      setPendingTask(null);
      void performSelect(task);
    };
    window.addEventListener("keydown", confirm);
    return () => window.removeEventListener("keydown", confirm);
  }, [pendingTask, switching, selected]);

  const seenKey = annotator ? "xmer-guide-seen-" + annotator : "";
  useEffect(() => {
    if (!ready || !seenKey || profile?.phase !== "training") return;
    if (remembered(seenKey, "") === "yes") return;
    setBook(true);
  }, [ready, seenKey, profile?.phase]);

  const closeBook = () => {
    setBook(false);
    try {
      if (seenKey) localStorage.setItem(seenKey, "yes");
    } catch {
      /* 隐私模式下存不下，最多下次再弹一遍，不值得打断 */
    }
  };

  // 一段刚刚标完就展开这一段的对照。挂在「完成的模态集合」上而不是提交回调：
  // 完成以服务端确认为准，等云端确认之后再复盘才不会拿本地的半成品作数。
  //
  // 「看过了」必须记在 localStorage 而不是内存：只记在内存的话，刷新一次
  // 就把已经看过的那几段重弹一遍，而标注者刷新是常事（断网重连、换设备）。
  const training = profile?.phase === "training";
  const finished = training
    ? completeModalities(tasks, attempts, submissions)
    : [];
  const reviewedKey = annotator ? "xmer-reviewed-" + annotator : "";
  useEffect(() => {
    if (!training || !reviewedKey || book) return;
    const seen = new Set(remembered(reviewedKey, "").split(",").filter(Boolean));
    const fresh = finished.find((modality) => !seen.has(modality));
    if (!fresh) return;
    seen.add(fresh);
    try {
      localStorage.setItem(reviewedKey, [...seen].join(","));
    } catch {
      /* 存不下最多下次再弹一遍，不值得打断 */
    }
    setReviewing(fresh);
  }, [finished.join(","), training, reviewedKey, book]);

  const doneCount = completedCount(tasks, attempts, submissions);
  const allDone = allComplete(tasks, attempts, submissions);

  // 从「还差一点」翻到「全齐了」的那一刻自动弹收尾页。挂在 allDone 上而不是
  // 提交回调上：勾以服务端为准，等云端确认之后再庆祝才不会庆祝一场空。
  const wasAllDone = useRef(false);
  useEffect(() => {
    if (allDone && !wasAllDone.current) setCelebrating(true);
    wasAllDone.current = allDone;
  }, [allDone]);

  const selectedTask = tasks.find((task) => task.task_id === selected);
  const selectedLocation = selectedTask
    ? locationOf(tasks, selectedTask.task_id)
    : null;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label={t("app.title")}>
          <span className="brand-mark">
            <Activity size={23} />
          </span>
          <strong>
            XMER<span>ANNOTATION</span>
          </strong>
        </div>
        <div className="header-actions">
          {/* 管理员镜像号：页面与标注者一比一，外加这一组切换，标注者看不到 */}
          {profile?.mirror && (
            <div className="mirror-switch" role="group" aria-label={t("mirror.badge")}>
              <span className="mirror-badge">{t("mirror.badge")}</span>
              {(["training", "main"] as const).map((view) => (
                <button
                  key={view}
                  className={profile.phase === view ? "active" : ""}
                  aria-pressed={profile.phase === view}
                  onClick={() => profile.phase !== view && switchMirrorView(view)}
                >
                  {t(view === "training" ? "mirror.training" : "mirror.main")}
                </button>
              ))}
            </div>
          )}
          {profile && (
            <div className="annotator-identity">
              <span className="identity-text">
                <strong>{profile.name}</strong>
              </span>
            </div>
          )}
          <button className="ghost book-open" onClick={() => setBook(true)}>
            <BookOpen size={15} />
            {t("book.reopen")}
          </button>
          {/* 正式阶段回看训练：只读，看素材、自己当时的曲线、参考曲线与解释。
              训练阶段不需要——侧栏每段标完就有「看对比」。 */}
          {!training && !!profile?.trainedModalities.length && (
            <button
              className="ghost book-open"
              onClick={() => setPickingReview(true)}
            >
              <GraduationCap size={15} />
              {t("review.open")}
            </button>
          )}
          <LangSwitch />
        </div>
      </header>

      {error && (
        <div className="global-error" role="alert">
          {error}
          <button onClick={() => location.reload()}>{t("step.redo")}</button>
        </div>
      )}

      {ready && selectedTask && selectedLocation ? (
        <div className="app-body">
          <TaskSidebar
            tasks={tasks}
            selected={selected}
            annotator={annotator}
            attempts={attempts}
            submissions={submissions}
            disabled={switching}
            onSelect={requestSelect}
            onReview={training ? setReviewing : undefined}
          />
          <Workspace
            key={annotator + selected + reload}
            task={selectedTask}
            position={selectedLocation.position}
            sectionTotal={selectedLocation.total}
            annotator={annotator}
            repository={repository}
            attempts={attempts}
            submissions={submissions}
            refresh={refresh}
            register={(session) => {
              activeSession.current = session;
            }}
            onNext={() => {
              const index = tasks.indexOf(selectedTask);
              const next = tasks[index + 1];
              // 最后一条的「下一个」通向收尾页。从前这里什么也不做，
              // 标完最后一遍的人得不到任何了结的信号。
              if (next) requestSelect(next);
              else setCelebrating(true);
            }}
            onReload={() => {
              void (async () => {
                try {
                  await activeSession.current?.leave();
                  setReload((value) => value + 1);
                } catch {
                  setError(t("err.waitSave"));
                }
              })();
            }}
            sync={sync}
            onGuide={() => setPendingTask(selectedTask)}
          />
        </div>
      ) : ready && !tasks.length ? (
        <div className="loading-workspace">
          <Activity size={28} />
          <p>{t("app.noTasks")}</p>
          <small>{t("app.refreshHint")}</small>
        </div>
      ) : (
        !error && (
          <div className="loading-workspace">
            <Activity size={28} />
            <p>{t("app.loadingWorkspace")}</p>
          </div>
        )
      )}

      {book && (
        <div className="book-backdrop">
          <GuideBook
            onStart={closeBook}
            startLabel={
              remembered(seenKey, "") === "yes" ? "book.close" : "book.start"
            }
          />
        </div>
      )}

      {pickingReview && profile && (
        <div className="modal-backdrop" onClick={() => setPickingReview(false)}>
          <section
            className="modality-guide review-picker"
            role="dialog"
            aria-modal="true"
            aria-labelledby="review-picker-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="review-picker-title">{t("review.title")}</h2>
            <p className="guide-lead">{t("review.lead")}</p>
            <div className="review-picker-list">
              {profile.trainedModalities.map((modality) => (
                <button
                  key={modality}
                  onClick={() => {
                    setPickingReview(false);
                    setReviewing(modality);
                  }}
                >
                  {t(("modality." + modality) as Key)}
                </button>
              ))}
            </div>
            <button className="ghost" onClick={() => setPickingReview(false)}>
              {t("debrief.close")}
            </button>
          </section>
        </div>
      )}

      {reviewing && (
        <Debrief modality={reviewing} onClose={() => setReviewing(null)} />
      )}

      {/* 最后一段训练的复盘和收尾页会同时触发：先让人看完复盘再盖收尾页，
          否则点「开始正式标注」一刷新，那一段的对照就再也看不到了 */}
      {celebrating && !reviewing && (
        <AllDone
          completed={doneCount}
          onBack={() => setCelebrating(false)}
          // 训练与正式同一个账号：重新加载时服务端判定训练已交齐，下发正式队列
          onStartMain={training ? () => location.reload() : undefined}
        />
      )}

      {pendingTask && (
        <div className="modal-backdrop">
          <section
            className="modality-guide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modality-guide-title"
          >
            <h2 id="modality-guide-title">
              {t(("modality." + pendingTask.modality) as Key)} ·{" "}
              {t("guide.title")}
            </h2>
            <p className="guide-lead">
              {t(("lead." + pendingTask.modality) as Key)}
            </p>

            <h3>{t("guide.dims")}</h3>
            <dl className="guide-dims">
              <dt>{t("dim.valence")}</dt>
              <dd>{t("guide.valence")}</dd>
              <dt>{t("dim.arousal")}</dt>
              <dd>
                {t("guide.arousal")}
                <em>{t("guide.arousalNote")}</em>
              </dd>
            </dl>

            <h3>{t("guide.how")}</h3>
            <ul className="guide-steps">
              <li>{t("guide.how1")}</li>
              <li>{t("guide.move")}</li>
              <li>{t("guide.how2")}</li>
            </ul>

            <h3>{t("guide.status")}</h3>
            <ul className="guide-steps">
              <li>{t("guide.status1")}</li>
            </ul>

            <div className="guide-ops">
              <span>
                <MousePointerClick size={16} aria-hidden="true" />
                {t("guide.opHold")}
              </span>
              <span>
                <MousePointer size={16} aria-hidden="true" />
                {t("guide.opRelease")}
              </span>
              <span>
                <CornerDownLeft size={16} aria-hidden="true" />
                {t("guide.opEnter")}
              </span>
            </div>
            <div className="modality-guide-actions">
              {pendingTask.task_id !== selected && (
                <button onClick={() => setPendingTask(null)}>{t("step.cancel")}</button>
              )}
              <button
                className="button primary"
                onClick={() => {
                  const task = pendingTask;
                  setPendingTask(null);
                  void performSelect(task);
                }}
              >
                {pendingTask.task_id === selected ? t("step.gotIt") : t("step.start")}
                <kbd>
                  <CornerDownLeft size={15} />
                  {t("step.enter")}
                </kbd>
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
