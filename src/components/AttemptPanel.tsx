import { History } from "lucide-react";
import { formatDate } from "../config";
import type { Attempt, SessionView, Submission } from "../types";
interface Props {
  attempts: Attempt[];
  current: Attempt | null;
  submissions: Submission[];
  view: SessionView;
  selected: string;
  onSelect: (id: string) => void;
  busy: boolean;
}
export default function AttemptPanel({
  attempts,
  current,
  submissions,
  view,
  selected,
  onSelect,
  busy,
}: Props) {
  const latest = submissions.at(-1);
  const active = [
    "recording",
    "preview",
    "paused",
    "starting",
    "buffering",
  ].includes(view.phase);
  const status = {
    recording: "进行中",
    paused: "已暂停",
    completed: "已完成",
    interrupted: "已中断",
  };
  // 收起来的折叠块：采样点数和提交状态留在标题行，轮次、时间这些按需展开。
  return (
    <details className="panel attempt-panel" aria-label="标注结果">
      <summary>
        <span className="attempt-state">
          {current ? status[current.status] : "未开始"}
        </span>
        <span>
          本轮 <strong data-testid="sample-count">{current?.sample_count ?? 0}</strong> 个采样点
        </span>
        <span className="attempt-revision">
          {latest ? "已提交 V" + latest.revision : "尚未提交"}
        </span>
        <small>展开查看轮次与时间</small>
      </summary>
      <div className="result-metrics">
        <div>
          <span>本轮完成时间</span>
          <strong className="date-value">
            {formatDate(current?.completed_at)}
          </strong>
        </div>
        <div>
          <span>当前提交版本</span>
          <strong>
            {latest ? "V" + latest.revision : "—"}
            <small>{latest ? " · 本地" : " 尚未提交"}</small>
          </strong>
        </div>
      </div>
      <div className="result-actions">
        <label className="history-select">
          <History size={15} />
          <select
            aria-label="历史标注轮次"
            value={selected}
            onChange={(e) => onSelect(e.target.value)}
            disabled={active || busy}
          >
            <option value="">当前轮次</option>
            {attempts
              .filter((a) => a.mode === "annotation")
              .map((a, i) => (
                <option key={a.attempt_id} value={a.attempt_id}>
                  第 {i + 1} 轮 · {status[a.status]}
                </option>
              ))}
          </select>
        </label>
      </div>
      {latest && (
        <p className="submission-time">
          首次提交：{formatDate(latest.submitted_at)}
          {latest.updated_at && "　最近更新：" + formatDate(latest.updated_at)}
        </p>
      )}
    </details>
  );
}
