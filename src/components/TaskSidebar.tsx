import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Film,
  Headphones,
  Layers3,
  Search,
  Type,
  Video,
} from "lucide-react";
import { formatTime, MODALITY_LABELS } from "../config";
import type { Attempt, Modality, Submission, Task } from "../types";
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
// 完整视频排最后：先看完整视频会让随后的单模态标注变成回忆而非感知，
// 而模态间的不一致正是本研究的因变量。说话主体改由静帧参考给出。
const MODALITY_ORDER: Record<Modality, number> = {
  visual: 0,
  audio: 1,
  text: 2,
  audiovisual: 3,
};
interface Group {
  display_id: string;
  demo: boolean;
  tasks: Task[];
}
function groupTasks(tasks: Task[]): Group[] {
  const order: string[] = [];
  const map = new Map<string, Task[]>();
  for (const t of tasks) {
    if (!map.has(t.display_id)) {
      map.set(t.display_id, []);
      order.push(t.display_id);
    }
    map.get(t.display_id)!.push(t);
  }
  return order.map((id) => {
    const list = map
      .get(id)!
      .slice()
      .sort((a, b) => MODALITY_ORDER[a.modality] - MODALITY_ORDER[b.modality]);
    return { display_id: id, demo: list.every((t) => t.demo), tasks: list };
  });
}
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
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // 展开当前选中任务所在的样本组
  const selectedSample = tasks.find((t) => t.task_id === selected)?.display_id;
  useEffect(() => {
    if (selectedSample)
      setExpanded((prev) => new Set(prev).add(selectedSample));
  }, [selectedSample]);

  const matchQuery = (t: Task) =>
    (t.display_id + MODALITY_LABELS[t.modality])
      .toLowerCase()
      .includes(query.toLowerCase());
  const matchFilter = (t: Task) =>
    filter === "all" ||
    (filter === "done" ? complete.has(t.task_id) : !complete.has(t.task_id));

  const allGroups = groupTasks(tasks);
  // 进度按样本算：四个模态只标完两个，这个样本就还没完成。
  // 按任务算会显示 60/80，让人以为快标完了，其实只有 15 个样本是齐的。
  const doneSamples = allGroups.filter((g) =>
    g.tasks.every((t) => complete.has(t.task_id)),
  ).length;

  const groups = allGroups
    .map((g) => ({
      ...g,
      tasks: g.tasks.filter((t) => matchQuery(t) && matchFilter(t)),
    }))
    .filter((g) => g.tasks.length > 0);

  const statusOf = (task: Task) => {
    const history = attempts.filter(
      (a) => a.task_id === task.task_id && a.mode === "annotation",
    );
    const latest = history.at(-1);
    const latestSubmitted =
      latest && submissions.some((s) => s.attempt_id === latest.attempt_id);
    return latest?.status === "completed" && !latestSubmitted
      ? complete.has(task.task_id)
        ? "待更新"
        : "待提交"
      : complete.has(task.task_id)
        ? "已提交"
        : latest
          ? "进行中"
          : "未开始";
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-heading">
        <Layers3 size={18} />
        <h2>样本目录</h2>
        <span>{allGroups.length}</span>
      </div>
      <div className="overall-progress">
        <div>
          <span>标注进度</span>
          <strong>
            {doneSamples}
            <small> / {allGroups.length} 个样本</small>
          </strong>
        </div>
        {/* 数字按样本，进度条按任务——这样标完一个模态也能看到条在动 */}
        <progress
          aria-label="总体标注进度"
          max={tasks.length}
          value={complete.size}
        />
        <p>
          {doneSamples === allGroups.length
            ? "本组样本已全部提交"
            : "四个模态都提交，这个样本才算完成。"}
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
      <nav className="sample-list" aria-label="样本目录">
        {groups.map((group) => {
          const isOpen = expanded.has(group.display_id);
          const doneCount = group.tasks.filter((t) =>
            complete.has(t.task_id),
          ).length;
          const allDone = doneCount === group.tasks.length;
          return (
            <div
              key={group.display_id}
              className={"sample-group " + (isOpen ? "open" : "")}
            >
              <button
                className="sample-header"
                aria-expanded={isOpen}
                onClick={() =>
                  setExpanded((prev) => {
                    const next = new Set(prev);
                    next.has(group.display_id)
                      ? next.delete(group.display_id)
                      : next.add(group.display_id);
                    return next;
                  })
                }
              >
                {isOpen ? (
                  <ChevronDown size={15} />
                ) : (
                  <ChevronRight size={15} />
                )}
                <span className="sample-name">
                  {group.demo ? "演示样本" : group.display_id}
                </span>
                {allDone ? (
                  <Check size={15} className="teal-text" />
                ) : (
                  <span className="sample-count">
                    {doneCount}/{group.tasks.length}
                  </span>
                )}
              </button>
              {isOpen && (
                <div className="sample-children">
                  {group.tasks.map((task) => {
                    const Icon = icons[task.modality];
                    const done = complete.has(task.task_id);
                    return (
                      <button
                        key={task.task_id}
                        className={
                          "modality-item " +
                          (selected === task.task_id ? "selected" : "")
                        }
                        onClick={() => onSelect(task)}
                        disabled={disabled}
                        aria-current={
                          selected === task.task_id ? "true" : undefined
                        }
                      >
                        <span className={"modality-icon " + task.modality}>
                          <Icon size={15} />
                        </span>
                        <span className="modality-text">
                          <strong>{MODALITY_LABELS[task.modality]}</strong>
                          <small>{formatTime(task.duration)}</small>
                        </span>
                        <span
                          className={
                            "modality-status " + (done ? "teal-text" : "")
                          }
                        >
                          {statusOf(task)}
                        </span>
                        {done && <Check size={14} className="teal-text" />}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        {!groups.length && <p className="empty-list">没有匹配的样本</p>}
      </nav>
      {/* V1 的旧文案写着"结果保存在当前浏览器、请及时导出备份"——
          现在结果直接进云端数据库，那句话会让人以为关掉浏览器就丢数据 */}
      <div className="sidebar-foot">
        <i className="dot teal" />
        <span>
          云端工作区 <small>V3.0</small>
        </span>
        <p>
          结果自动同步到服务器
          <br />
          断网可继续标注，恢复后补传
        </p>
      </div>
    </aside>
  );
}
