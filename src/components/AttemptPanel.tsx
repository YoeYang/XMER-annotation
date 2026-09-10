import { CheckCircle2, Download, History, RotateCcw, Send } from "lucide-react";
import { formatDate } from "../config";
import type { Attempt, SessionView, Submission } from "../types";
interface Props {
  attempts: Attempt[];
  current: Attempt | null;
  submissions: Submission[];
  view: SessionView;
  selected: string;
  onSelect: (id: string) => void;
  onSubmit: () => void;
  onReset: () => void;
  onExport: () => void;
  busy: boolean;
}
export default function AttemptPanel({
  attempts,
  current,
  submissions,
  view,
  selected,
  onSelect,
  onSubmit,
  onReset,
  onExport,
  busy,
}: Props) {
  const latest = submissions.at(-1),
    already = submissions.some((s) => s.attempt_id === current?.attempt_id);
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
  return (
    <section className="panel attempt-panel" aria-label="标注结果">
      <div className="attempt-summary">
        <div className="result-icon">
          <CheckCircle2 size={21} />
        </div>
        <div>
          <h2>
            {current?.status === "completed"
              ? "本轮记录已完成"
              : "记录你的每一刻感知"}
          </h2>
          <p>
            {current?.status === "completed"
              ? "检查轮次后提交；如需调整，可以重新标注。"
              : "点击二维区域开始，播放结束后自动保存本轮结果。"}
          </p>
        </div>
      </div>
      <div className="result-metrics">
        <div>
          <span>原始采样点</span>
          <strong data-testid="sample-count">
            {current?.sample_count ?? 0}
            <small> 点</small>
          </strong>
        </div>
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
        <div className="action-buttons">
          <button
            className="button secondary"
            onClick={onExport}
            disabled={
              busy ||
              ["starting", "recording", "preview", "buffering"].includes(
                view.phase,
              )
            }
          >
            <Download size={15} />
            导出 JSON
          </button>
          <button
            className="button secondary"
            onClick={onReset}
            disabled={
              busy ||
              ["loading", "starting", "error"].includes(view.phase) ||
              (!view.attempt && !current)
            }
          >
            <RotateCcw size={15} />
            重新标注
          </button>
          <button
            className="button primary"
            onClick={onSubmit}
            disabled={
              busy ||
              active ||
              current?.status !== "completed" ||
              !current.sample_count ||
              already
            }
          >
            <Send size={15} />
            {already ? "已提交" : latest ? "Update 更新" : "Submit 提交"}
          </button>
        </div>
      </div>
      {latest && (
        <p className="submission-time">
          首次提交：{formatDate(latest.submitted_at)}
          {latest.updated_at && "　最近更新：" + formatDate(latest.updated_at)}
        </p>
      )}
    </section>
  );
}
