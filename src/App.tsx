import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  BookOpen,
  Check,
  HardDrive,
  X,
} from "lucide-react";
import { IndexedDbRepository } from "./storage/indexedDbRepository";
import { validateTasks } from "./core/textTimeline";
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
  const [repository] = useState(() => new IndexedDbRepository());
  const [tasks, setTasks] = useState<Task[]>([]),
    [selected, setSelected] = useState(remembered("xmer-task", ""));
  const [annotator, setAnnotator] = useState(
      remembered("xmer-annotator", "A001"),
    ),
    [draftId, setDraftId] = useState(annotator);
  const [attempts, setAttempts] = useState<Attempt[]>([]),
    [submissions, setSubmissions] = useState<Submission[]>([]);
  const [error, setError] = useState(""),
    [ready, setReady] = useState(false),
    [locked, setLocked] = useState(false);
  const [help, setHelp] = useState(false),
    [switching, setSwitching] = useState(false),
    [reload, setReload] = useState(0);
  const activeSession = useRef<AnnotationSession | null>(null);
  const refresh = useCallback(async () => {
    const [a, s] = await Promise.all([
      repository.listAttempts(annotator),
      repository.listSubmissions(annotator),
    ]);
    setAttempts(a);
    setSubmissions(s);
  }, [repository, annotator]);
  useEffect(() => {
    let release: (() => void) | undefined,
      cancelled = false;
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
      .catch((e) => setError(String(e)));
    return () => {
      cancelled = true;
      release?.();
    };
  }, []);
  useEffect(() => {
    if (!locked) return;
    let cancelled = false;
    setReady(false);
    void (async () => {
      try {
        const response = await fetch("/tasks.json");
        if (!response.ok)
          throw new Error("样本目录加载失败，请检查 tasks.json");
        const list = validateTasks(await response.json());
        await repository.recoverInterrupted(annotator);
        const [a, s] = await Promise.all([
          repository.listAttempts(annotator),
          repository.listSubmissions(annotator),
        ]);
        if (cancelled) return;
        setTasks(list);
        setSelected((old) =>
          list.some((t) => t.task_id === old) ? old : list[0].task_id,
        );
        setAttempts(a);
        setSubmissions(s);
        setReady(true);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "本地工作区读取失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [locked, annotator, repository]);
  const remember = (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      setError("无法记住工作区设置；标注结果仍以本地数据库保存状态为准。");
    }
  };
  const selectTask = async (task: Task) => {
    if (switching || task.task_id === selected) return;
    setSwitching(true);
    try {
      await activeSession.current?.leave();
      setSelected(task.task_id);
      remember("xmer-task", task.task_id);
    } catch {
      setError("当前轮次保存失败，请重试保存或导出后再切换样本。");
    } finally {
      setSwitching(false);
    }
  };
  const exportAll = async () => {
    const data = activeSession.current
      ? await activeSession.current.exportData()
      : await repository.export(annotator);
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download =
      "xmer-" +
      annotator +
      "-" +
      new Date().toISOString().replace(/[:.]/g, "-") +
      ".json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const selectedTask = tasks.find((t) => t.task_id === selected);
  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href="/"
          onClick={(e) => e.preventDefault()}
          aria-label="XMER 标注工作台"
        >
          <span className="brand-mark">
            <Activity size={23} />
          </span>
          <strong>
            XMER<span>ANNOTATION</span>
          </strong>
        </a>
        <div className="topbar-center">
          多模态情感研究<span>/</span>标注工作台
        </div>
        <div className="header-actions">
          <span className="local-badge">
            <HardDrive size={14} />
            本地模式
          </span>
          <button className="header-help" onClick={() => setHelp(true)}>
            <BookOpen size={16} />
            标注指南
          </button>
          <form
            className="annotator-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!draftId.trim() || switching) return;
              setSwitching(true);
              void (async () => {
                try {
                  await activeSession.current?.leave();
                  remember("xmer-annotator", draftId.trim());
                  setAnnotator(draftId.trim());
                } catch {
                  setError("保存失败，暂时无法切换标注者");
                } finally {
                  setSwitching(false);
                }
              })();
            }}
          >
            <span className="avatar">
              {annotator.slice(0, 1).toUpperCase()}
            </span>
            <label>
              <span>标注者</span>
              <input
                aria-label="标注者编号"
                value={draftId}
                maxLength={40}
                pattern="[A-Za-z0-9_-]+"
                title="使用英文字母、数字、下划线或短横线"
                onChange={(e) => setDraftId(e.target.value)}
              />
            </label>
            {draftId !== annotator && (
              <button aria-label="应用标注者编号" disabled={switching}>
                <Check size={15} />
              </button>
            )}
          </form>
        </div>
      </header>
      {error && (
        <div className="global-error" role="alert">
          {error}
          <button onClick={() => location.reload()}>重新加载</button>
        </div>
      )}
      {ready && selectedTask ? (
        <div className="app-body">
          <TaskSidebar
            tasks={tasks}
            selected={selected}
            attempts={attempts}
            submissions={submissions}
            disabled={switching}
            onSelect={(task) => void selectTask(task)}
          />
          <Workspace
            key={annotator + selected + reload}
            task={selectedTask}
            index={tasks.indexOf(selectedTask)}
            total={tasks.length}
            annotator={annotator}
            repository={repository}
            attempts={attempts}
            submissions={submissions}
            refresh={refresh}
            register={(session) => {
              activeSession.current = session;
            }}
            onNext={() => {
              const next = tasks[tasks.indexOf(selectedTask) + 1];
              if (next) void selectTask(next);
            }}
            onReload={() => {
              void (async () => {
                try {
                  await activeSession.current?.leave();
                  setReload((n) => n + 1);
                } catch {
                  setError("请先重试保存当前记录。");
                }
              })();
            }}
            onExport={exportAll}
          />
        </div>
      ) : (
        !error && (
          <div className="loading-workspace">
            <Activity size={28} />
            <p>正在读取你的标注工作区…</p>
          </div>
        )
      )}
      {help && (
        <div className="modal-backdrop" onClick={() => setHelp(false)}>
          <section
            className="guide-modal"
            role="dialog"
            aria-modal="true"
            aria-label="标注指南"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close-guide icon-button"
              aria-label="关闭指南"
              onClick={() => setHelp(false)}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">A SMALL GUIDE</span>
            <h2>让感知，随时间被记录。</h2>
            <ol>
              <li>
                <strong>选择一个样本</strong>
                <p>先通过播放按钮预览材料，了解标注对象。</p>
              </li>
              <li>
                <strong>点击方形，开始标注</strong>
                <p>
                  横向表示负面到正面，纵向表示低唤醒到高唤醒。点击后媒体归零，立即记录初始位置。
                </p>
              </li>
              <li>
                <strong>随情绪移动光标</strong>
                <p>
                  无需按住鼠标，静止或离开区域仍持续记录。暂停、缓冲或切到后台时停止采样；返回后点击继续。
                </p>
              </li>
              <li>
                <strong>检查后提交</strong>
                <p>
                  完成后自动保存草稿。首次 Submit，重新标注后
                  Update；所有历史轮次均保留。第一版修改通过重新标注完成。
                </p>
              </li>
            </ol>
            <p className="guide-local">
              <ArrowDownToLine size={18} />
              第一版结果仅保存在当前浏览器。请导出 JSON
              备份，清除浏览器数据会删除本地记录。
            </p>
            <button className="button primary" onClick={() => setHelp(false)}>
              我知道了，开始标注
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
