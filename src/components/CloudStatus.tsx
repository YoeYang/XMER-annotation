import { Cloud, CloudOff, Loader, TriangleAlert } from "lucide-react";
import type { SyncState } from "../storage/syncingRepository";

/**
 * 云端同步状态，常驻显示。
 *
 * 标注者交出去的东西要看得见去向。原先只在出错时冒一句「已保存，联网后上传」，
 * 平时什么都不说——人无从知道结果到底进没进云端，只能猜。
 *
 * 提交不等上传（等一次网络往返会让「下一步」卡住），所以这里是唯一能
 * 如实交代进度的地方：传完了说传完了，还在传说还在传，传不动说传不动。
 */
export default function CloudStatus({
  sync,
  saveError,
}: {
  sync: SyncState | null;
  saveError?: string | null;
}) {
  if (saveError) {
    return (
      <p className="cloud-status failed" role="status">
        <TriangleAlert size={15} aria-hidden="true" />
        保存失败：{saveError}
      </p>
    );
  }
  if (!sync) return null;

  if (sync.pending > 0) {
    // 有待传的东西时，区分「正在传」与「传不动」——后者才需要人操心
    const stuck = !sync.syncing && sync.lastError;
    return (
      <p className={"cloud-status " + (stuck ? "waiting" : "uploading")} role="status">
        {stuck ? (
          <CloudOff size={15} aria-hidden="true" />
        ) : (
          <Loader size={15} className="spin" aria-hidden="true" />
        )}
        {stuck
          ? `已存在本机，等网络恢复后自动上传（${sync.pending} 条待传）`
          : `正在上传到云端…（${sync.pending} 条）`}
      </p>
    );
  }

  return (
    <p className="cloud-status synced" role="status">
      <Cloud size={15} aria-hidden="true" />
      {sync.lastSyncedAt ? "已上传到云端" : "已连接云端"}
    </p>
  );
}
