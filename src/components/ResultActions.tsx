import { Download, RotateCcw, Send } from "lucide-react";
import type { Attempt, SessionView, Submission } from "../types";
interface Props {
  current: Attempt | null;
  submissions: Submission[];
  view: SessionView;
  onSubmit: () => void;
  onReset: () => void;
  onExport: () => void;
  busy: boolean;
}
/**
 * 一次标注的收尾动作。放在标注罗盘的标题栏里：
 * 原本在页面底部，每标完一个任务都要往下滚一次，一次标注跑不完一屏。
 */
export default function ResultActions({
  current,
  submissions,
  view,
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
  return (
    <div className="action-buttons">
      <button
        className="button secondary"
        onClick={onExport}
        title="导出本任务的原始标注 JSON"
        disabled={
          busy ||
          ["starting", "recording", "preview", "buffering"].includes(view.phase)
        }
      >
        <Download size={15} />
        导出
      </button>
      <button
        className="button secondary"
        onClick={onReset}
        title="保留已有轮次，重新标注一轮"
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
        {already ? "已提交" : latest ? "更新" : "提交"}
      </button>
    </div>
  );
}
