import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, CornerDownLeft } from "lucide-react";
import { IndexedDbRepository } from "./storage/indexedDbRepository";
import { HttpRepository } from "./storage/httpRepository";
import { SyncingRepository } from "./storage/syncingRepository";
import type { SyncState } from "./storage/syncingRepository";
import { captureToken, getToken } from "./auth";
import { validateTasks } from "./core/textTimeline";
import { locationOf, orderedTasks } from "./core/taskFlow";
import { API_BASE } from "./config";
import LangSwitch from "./components/LangSwitch";
import { useLang } from "./LangContext";
import type { Key } from "./i18n";
import type { AnnotationSession } from "./core/session";
import type { Attempt, Submission, Task } from "./types";
import TaskSidebar from "./components/TaskSidebar";
import Workspace from "./components/Workspace";

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
  } | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [locked, setLocked] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [reload, setReload] = useState(0);
  const [pendingTask, setPendingTask] = useState<Task | null>(null);
  const [sync, setSync] = useState<SyncState | null>(null);
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
        "请通过 localhost 或 HTTPS 打开，并使用支持 Web Locks 的现代浏览器。",
      );
      return;
    }
    void navigator.locks
      .request("xmer-local-editor", { ifAvailable: true }, async (lock) => {
        if (cancelled) return;
        if (!lock) {
          setError("另一个页面正在使用本地工作区，请关闭该页面后重新加载。");
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
        const response = await fetch(API_BASE + "/me", {
          headers: { authorization: "Bearer " + token },
        });
        if (response.status === 401 || response.status === 403)
          throw new Error(t("err.badToken"));
        if (!response.ok) throw new Error(t("err.offline"));
        const me = await response.json();
        if (cancelled) return;
        setAnnotator(me.annotator_id);
        setProfile({
          name: me.display_name || me.annotator_id,
          phase: me.phase,
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
      setError("无法记住当前任务；标注结果仍会保存在本地数据库。");
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
      setError("当前轮次保存失败，请稍后重试。");
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

  const selectedTask = tasks.find((task) => task.task_id === selected);
  const selectedLocation = selectedTask
    ? locationOf(tasks, selectedTask.task_id)
    : null;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label="XMER 标注工作台">
          <span className="brand-mark">
            <Activity size={23} />
          </span>
          <strong>
            XMER<span>ANNOTATION</span>
          </strong>
        </div>
        <div className="header-actions">
          {profile && (
            <div className="annotator-identity">
              <span className="identity-text">
                <strong>{profile.name}</strong>
              </span>
            </div>
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
              if (next) requestSelect(next);
            }}
            onReload={() => {
              void (async () => {
                try {
                  await activeSession.current?.leave();
                  setReload((value) => value + 1);
                } catch {
                  setError("请先等待当前记录保存完成。");
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
          <p>研究者尚未给你分配任务。</p>
          <small>分配完成后刷新本页即可开始。</small>
        </div>
      ) : (
        !error && (
          <div className="loading-workspace">
            <Activity size={28} />
            <p>正在读取你的标注工作区…</p>
          </div>
        )
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
              {t(("modality." + pendingTask.modality) as Key)} · {t("guide.title")}
            </h2>
            <p>
              {
t(("guide." + pendingTask.modality) as Key)
              }
            </p>
            <p>
              {t("guide.how")}
            </p>
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
