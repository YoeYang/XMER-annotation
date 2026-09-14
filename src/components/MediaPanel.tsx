import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Headphones,
  Pause,
  Play,
  RotateCcw,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  formatTime,
  MODALITY_LABELS,
  PHASE_LABELS,
  PLAYBACK_RATES,
  resolveAssetPath,
} from "../config";
import type { SessionView, Task, Transcript } from "../types";
import {
  silentWav,
  transcriptTokens,
  validateTranscript,
} from "../core/textTimeline";
import type { AnnotationSession } from "../core/session";
interface Props {
  task: Task;
  session: AnnotationSession;
  view: SessionView;
  onReload: () => void;
}
export default function MediaPanel({ task, session, view, onReload }: Props) {
  const element = useRef<HTMLMediaElement | null>(null);
  const [source, setSource] = useState(
    task.modality === "text" ? "" : resolveAssetPath(task.src),
  );
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  useEffect(() => {
    if (task.modality !== "text") return;
    const controller = new AbortController();
    let objectUrl = "";
    void (async () => {
      try {
        const response = await fetch(resolveAssetPath(task.src), {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("文本文件加载失败");
        const data = validateTranscript(await response.json(), task.duration);
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(silentWav(task.duration));
        setTranscript(data);
        setSource(objectUrl);
      } catch (error) {
        if (!controller.signal.aborted)
          session.fail(error instanceof Error ? error.message : "文本加载失败");
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [task, session]);
  useEffect(() => {
    if (element.current && source) session.attach(element.current);
  }, [source, session]);
  const running = ["preview", "recording", "buffering"].includes(view.phase);
  const active =
    view.attempt && ["recording", "paused"].includes(view.attempt.status);
  const play = () => {
    if (running) session.pause();
    else if (view.phase === "paused") void session.resume();
    else void session.start("preview");
  };
  const disabled = ["loading", "starting", "error"].includes(view.phase);
  return (
    <section className="panel media-panel" aria-labelledby="media-title">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">01 / OBSERVE</span>
          <h2 id="media-title">观察当前材料</h2>
        </div>
        <span className="chip">{MODALITY_LABELS[task.modality]}</span>
      </div>
      {task.speaker_ref_src && (
        <figure className="speaker-ref">
          <img
            src={resolveAssetPath(task.speaker_ref_src)}
            alt={
              task.speaker_name ? "目标说话人 " + task.speaker_name : "目标说话人"
            }
          />
          <figcaption>
            <span className="eyebrow">目标说话人</span>
            <strong>按这个人进行标注</strong>
            {task.speaker_name && <small>{task.speaker_name}</small>}
          </figcaption>
        </figure>
      )}
      <div className={"media-stage " + task.modality}>
        {(task.modality === "visual" || task.modality === "audiovisual") && (
          <video
            ref={(node) => {
              element.current = node;
            }}
            src={source}
            preload="auto"
            playsInline
            muted={task.modality === "visual"}
            disablePictureInPicture
          />
        )}
        {(task.modality === "audio" || task.modality === "text") && source && (
          <audio
            ref={(node) => {
              element.current = node;
            }}
            src={source}
            preload="auto"
          />
        )}
        {task.modality === "audio" && (
          <div className="audio-scene">
            <div className="headphone-circle">
              <Headphones size={36} strokeWidth={1.3} />
            </div>
            <div className={"waveform " + (running ? "playing" : "")}>
              {Array.from({ length: 43 }, (_, i) => (
                <i
                  key={i}
                  style={{
                    height: 12 + ((i * 17 + i * i * 7) % 62) + "px",
                    animationDelay: i * -0.12 + "s",
                  }}
                />
              ))}
            </div>
            <p>专注聆听声音中的情绪</p>
            <small>示意波形 · 不代表真实音频振幅</small>
          </div>
        )}
        {task.modality === "text" && (
          <div className="text-scene">
            <span className="eyebrow">TIMED TRANSCRIPT</span>
            <p data-testid="transcript">
              {transcript
                ? transcriptTokens(transcript, view.time).map((token, i) => (
                    <span key={i} className={token.spoken ? "said" : ""}>
                      {token.lead}
                      {token.text}
                    </span>
                  ))
                : "文本载入中…"}
            </p>
            <small>高亮表示已经说到这里 · 按原始说话时间戳推进</small>
          </div>
        )}
        <span className="stage-label">
          {task.demo ? "DEMO / 演示素材" : "研究材料"}
        </span>
        <span className="stage-audio">
          {task.modality === "visual" || task.modality === "text" ? (
            <VolumeX size={15} />
          ) : (
            <Volume2 size={15} />
          )}
        </span>
      </div>
      <div className="media-controls">
        <progress
          aria-label="媒体播放进度"
          max={view.duration}
          value={view.time}
        />
        <div className="transport-row">
          <div className="transport-buttons">
            <button
              className="play-button"
              onClick={play}
              disabled={disabled}
              aria-label={
                running
                  ? "暂停播放"
                  : view.phase === "paused"
                    ? "继续播放"
                    : "预览材料"
              }
            >
              {running ? (
                <Pause size={18} fill="currentColor" />
              ) : (
                <Play size={18} fill="currentColor" />
              )}
            </button>
            <button
              className="icon-button"
              aria-label="重新开始"
              title="保留本轮，重新开始"
              disabled={disabled || !view.attempt}
              onClick={() => void session.reset().catch(() => {})}
            >
              <RotateCcw size={17} />
            </button>
            <span className="timecode" data-testid="media-time">
              {formatTime(view.time)} <span>/ {formatTime(view.duration)}</span>
            </span>
          </div>
          <label className="speed-label">
            倍速
            <select
              aria-label="播放速度"
              value={view.rate}
              disabled={view.phase === "starting"}
              onChange={(event) => session.setRate(Number(event.target.value))}
            >
              {PLAYBACK_RATES.map((rate) => (
                <option key={rate} value={rate}>
                  {rate}×
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="media-caption">
        <span
          className={"status-dot " + (view.phase === "recording" ? "live" : "")}
        />
        <span role="status">{PHASE_LABELS[view.phase]}</span>
        <span className="caption-right">
          {active && view.attempt?.mode === "annotation"
            ? "正式标注"
            : "可先预览熟悉材料"}
        </span>
      </div>
      {view.error && (
        <div className="inline-error" role="alert">
          <AlertCircle size={16} />
          <span>{view.error}</span>
          <button onClick={onReload}>重新加载</button>
        </div>
      )}
      <div className="target-note">
        <span>标注对象</span>
        <p>{task.target}</p>
      </div>
    </section>
  );
}
