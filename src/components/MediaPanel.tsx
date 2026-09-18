import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Headphones,
  Pause,
  Play,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  formatTime,
  MODALITY_LABELS,
  PLAYBACK_RATES,
  resolveAssetPath,
} from "../config";
import type { FlowPage, SessionView, Task, Transcript } from "../types";
import {
  silentWav,
  transcriptTokens,
  validateTranscript,
} from "../core/textTimeline";
import type { AnnotationSession } from "../core/session";

interface Props {
  task: Task;
  page: FlowPage;
  session: AnnotationSession;
  view: SessionView;
  onReload: () => void;
}

export default function MediaPanel({
  task,
  page,
  session,
  view,
  onReload,
}: Props) {
  const element = useRef<HTMLMediaElement | null>(null);
  const [source, setSource] = useState(
    task.modality === "text" ? "" : resolveAssetPath(task.src),
  );
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  const silentModality = ["face", "body", "text"].includes(task.modality);
  const [muted, setMuted] = useState(silentModality);

  useEffect(() => {
    if (task.modality !== "text") return;
    const controller = new AbortController();
    let objectUrl = "";
    void (async () => {
      try {
        const response = await fetch(resolveAssetPath(task.src), {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("文本文件加载失败 Text file failed");
        const data = validateTranscript(await response.json(), task.duration);
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(silentWav(task.duration));
        setTranscript(data);
        setSource(objectUrl);
      } catch (error) {
        if (!controller.signal.aborted)
          session.fail(error instanceof Error ? error.message : "文本加载失败 Text failed");
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [task, session]);

  useEffect(() => {
    if (!element.current || !source) return;
    session.attach(element.current);
  }, [source, session]);

  useEffect(() => {
    if (page !== "familiarization") {
      setAutoplayBlocked(false);
      return;
    }
    if (!element.current || !source) return;
    void session
      .startFamiliarization()
      .then((started) => setAutoplayBlocked(!started));
  }, [page, source, session]);

  const video = ["face", "body", "audiovisual"].includes(task.modality);
  const familiarization = page === "familiarization";
  const playing = familiarization && view.phase === "familiarizing";
  return (
    <section
      className="media-panel v3-media"
      aria-label={MODALITY_LABELS[task.modality]}
    >
      <div className="media-toolbar">
        <figure className="speaker-ref">
          {/* 身体模态不给静帧：那张脸正是画面里被遮住的部位，
              拿出来看等于把遮挡白做了——标注者会照着静帧上的表情判断，
              而这一轮要的恰恰是"看不见表情时，只凭肢体能读出什么"。 */}
          {task.modality !== "body" && task.speaker_ref_src && (
            <img
              src={resolveAssetPath(task.speaker_ref_src)}
              alt="目标说话人 Target speaker"
            />
          )}
          <figcaption>
            {task.modality === "body"
              ? "请标注被遮住脸部的人的肢体情绪\nRate the body language of the masked person"
              : task.speaker_ref_src
                ? "请标注这位说话人的情绪 Rate this speaker"
                : task.speaker_name
                  ? "说话人 Speaker：" + task.speaker_name
                  : "未提供说话人指示 No speaker reference"}
          </figcaption>
        </figure>
      </div>

      {task.modality === "audio" && view.rate === 0.1 && (
        <p className="rate-warning" role="status">
          0.1× 音频可能难以听清 · May be hard to hear
        </p>
      )}

      <div className={"media-stage " + task.modality}>
        {video && (
          <video
            ref={(node) => {
              element.current = node;
            }}
            src={source}
            preload="auto"
            playsInline
            muted={muted}
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
          </div>
        )}
        {task.modality === "text" && (
          <div className="text-scene">
            <p data-testid="transcript">
              {transcript
                ? transcriptTokens(transcript, view.time).map(
                    (token, index) => (
                      <span key={index} className={token.spoken ? "said" : ""}>
                        {token.lead}
                        {token.text}
                      </span>
                    ),
                  )
                : "载入中 Loading…"}
            </p>
          </div>
        )}
        <span className="stage-audio">
          {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
        </span>
        {autoplayBlocked && page === "familiarization" && (
          <button
            className="autoplay-fallback"
            onClick={() =>
              void session
                .startFamiliarization()
                .then((started) => setAutoplayBlocked(!started))
            }
          >
            <Play size={18} fill="currentColor" />
            点击开始熟悉
          </button>
        )}
      </div>

      <div className="media-controls">
        {familiarization && (
          <button
            className="media-control-button"
            aria-label={playing ? "暂停媒体" : "播放媒体"}
            onClick={() => void session.toggleFamiliarization()}
          >
            {playing ? (
              <Pause size={18} fill="currentColor" />
            ) : (
              <Play size={18} fill="currentColor" />
            )}
          </button>
        )}
        {familiarization ? (
          <input
            className="media-progress"
            type="range"
            aria-label="媒体播放进度"
            min="0"
            max={view.duration || task.duration}
            step="0.01"
            value={view.time}
            onChange={(event) =>
              session.seekFamiliarization(Number(event.target.value))
            }
          />
        ) : (
          <progress
            aria-label="媒体播放进度"
            max={view.duration}
            value={view.time}
          />
        )}
        <span data-testid="media-time">
          {formatTime(view.time)} / {formatTime(view.duration)}
        </span>
        <button
          className="media-control-button"
          aria-label={muted ? "打开声音" : "静音"}
          title={silentModality ? "本模态无声音 No audio" : undefined}
          disabled={silentModality}
          onClick={() => setMuted((value) => !value)}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <label className="speed-label">
          <select
            aria-label="播放速度"
            value={view.rate}
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

      {view.error && (
        <div className="inline-error" role="alert">
          <AlertCircle size={16} />
          <span>{view.error}</span>
          <button onClick={onReload}>重新加载</button>
        </div>
      )}
    </section>
  );
}
