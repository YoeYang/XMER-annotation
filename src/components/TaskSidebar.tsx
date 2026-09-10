import { useState } from "react";
import {
  Check,
  ChevronRight,
  Film,
  Headphones,
  Layers3,
  Search,
  Type,
  Video,
} from "lucide-react";
import { formatTime, MODALITY_LABELS } from "../config";
import type { Attempt, Submission, Task } from "../types";
interface Props {
  tasks: Task[];
  selected: string;
  attempts: Attempt[];
  submissions: Submission[];
  onSelect: (task: Task) => void;
  disabled: boolean;
}
const icons = {
  visual: Video,
  audio: Headphones,
  text: Type,
  audiovisual: Film,
};
export default function TaskSidebar({
  tasks,
  selected,
  attempts,
  submissions,
  onSelect,
  disabled,
}: Props) {
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all");
  const complete = new Set(submissions.map((s) => s.task_id));
  const visible = tasks.filter(
    (t) =>
      (t.title + t.task_id + MODALITY_LABELS[t.modality])
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "done"
          ? complete.has(t.task_id)
          : !complete.has(t.task_id))),
  );
  return (
    <aside className="sidebar">
      <div className="sidebar-heading">
        <Layers3 size={18} />
        <h2>样本目录</h2>
        <span>{tasks.length}</span>
      </div>
      <div className="overall-progress">
        <div>
          <span>标注进度</span>
          <strong>
            {complete.size}
            <small> / {tasks.length}</small>
          </strong>
        </div>
        <progress
          aria-label="总体标注进度"
          max={tasks.length}
          value={complete.size}
        />
        <p>
          {complete.size === tasks.length
            ? "本组样本已全部提交"
            : "每一份感知，都值得被记录。"}
        </p>
      </div>
      <label className="search-box">
        <Search size={15} />
        <input
          placeholder="搜索样本…"
          aria-label="搜索样本"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="filter-tabs" aria-label="样本筛选">
        {[
          ["all", "全部"],
          ["todo", "待完成"],
          ["done", "已提交"],
        ].map(([value, label]) => (
          <button
            key={value}
            aria-pressed={filter === value}
            className={filter === value ? "active" : ""}
            onClick={() => setFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <nav className="task-list" aria-label="样本目录">
        {visible.map((task) => {
          const Icon = icons[task.modality],
            history = attempts.filter(
              (a) => a.task_id === task.task_id && a.mode === "annotation",
            );
          const latest = history.at(-1);
          const latestSubmitted =
            latest &&
            submissions.some((s) => s.attempt_id === latest.attempt_id);
          const label =
            latest?.status === "completed" && !latestSubmitted
              ? complete.has(task.task_id)
                ? "待更新"
                : "待提交"
              : complete.has(task.task_id)
                ? "已提交"
                : latest
                  ? "进行中"
                  : "未开始";
          return (
            <button
              key={task.task_id}
              className={
                "task-item " + (selected === task.task_id ? "selected" : "")
              }
              onClick={() => onSelect(task)}
              disabled={disabled}
              aria-current={selected === task.task_id ? "true" : undefined}
            >
              <span className="task-item-top">
                <span className={"modality-icon " + task.modality}>
                  <Icon size={16} />
                </span>
                <span className="task-number">{task.task_id}</span>
                {complete.has(task.task_id) ? (
                  <Check size={15} className="teal-text" />
                ) : (
                  <ChevronRight size={14} />
                )}
              </span>
              <strong>{task.title}</strong>
              <span className="task-item-bottom">
                <span>
                  {MODALITY_LABELS[task.modality]} · {formatTime(task.duration)}
                </span>
                <span className={complete.has(task.task_id) ? "teal-text" : ""}>
                  {label}
                </span>
              </span>
            </button>
          );
        })}
        {!visible.length && <p className="empty-list">没有匹配的样本</p>}
      </nav>
      <div className="sidebar-foot">
        <i className="dot teal" />
        <span>
          本地工作区 <small>V1.0</small>
        </span>
        <p>
          结果保存在当前浏览器
          <br />
          请及时导出备份
        </p>
      </div>
    </aside>
  );
}
