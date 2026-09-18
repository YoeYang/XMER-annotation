import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Headphones,
  Pause,
  Play,
  Volume2,
  VolumeX,
} from "lucide-react";
import { useLang } from "../LangContext";
import type { Key } from "../i18n";
import {
  formatTime,
  PLAYBACK_RATES,
  resolveAssetPath,
} from "../config";
import type { FlowPage, SessionView, Task, Transcript } from "../types";
import {
  silentWav,
  transcriptLines,
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
  const { t } = useLang();
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
        if (!response.ok) throw new Error(t("media.textFailed"));
        const data = validateTranscript(await response.json(), task.duration);
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(silentWav(task.duration));
        setTranscript(data);
        setSource(objectUrl);
      } catch (error) {
        if (!controller.signal.aborted)
          session.fail(error instanceof Error ? error.message : t("media.textFailed"));
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
  /* 只有画面里有人可认的模态才给静帧：
     body 的那张脸正是画面里被遮住的部位，拿出来看等于把遮挡白做了；
     audio 与 text 根本没有画面，摆一张脸只会把判断往「这人长这样」上带，
     而这两轮要的恰恰是单凭语音韵律、单凭文字语义能读出什么。 */
  const showsSpeaker = ["face", "audiovisual"].includes(task.modality);
  // 没静帧也没名字时整块不显示——空着的说明栏只占地方
  const caption =
    task.modality === "body"
      ? t("speaker.masked")
      : showsSpeaker && task.speaker_ref_src
        ? t("speaker.rateThis")
        : task.speaker_name
          ? t("speaker.name") + "：" + task.speaker_name
          : null;
  const familiarization = page === "familiarization";
  const playing = familiarization && view.phase === "familiarizing";
  return (
    <section
      className="media-panel v3-media"
      aria-label={t(("modality." + task.modality) as Key)}
    >
      <div className="media-toolbar">
        {caption && (
          <figure className="speaker-ref">
            {showsSpeaker && task.speaker_ref_src && (
              <img
                src={resolveAssetPath(task.speaker_ref_src)}
                alt={t("speaker.target")}
              />
            )}
            <figcaption>{caption}</figcaption>
          </figure>
        )}
      </div>

      {task.modality === "audio" && view.rate === 0.1 && (
        <p className="rate-warning" role="status">
          {t("media.slowAudio")}
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
            {transcript ? (
              <div data-testid="transcript">
                {transcriptLines(transcript, view.time).map((line, index) => (
                  <p className="transcript-line" key={index}>
                    <span className="zh">
                      {line.tokens.map((token, i) => (
                        <span key={i} className={token.spoken ? "said" : ""}>
                          {token.lead}
                          {token.text}
                        </span>
                      ))}
                    </span>
                    {/* 中文逐词点亮、英文整句点亮：中英词序不同，
                        逐词对齐做不到，硬对齐会把译文切成看不懂的碎片 */}
                    {line.english && (
                      <span className={"en " + (line.spoken ? "said" : "")}>
                        {line.english}
                      </span>
                    )}
                  </p>
                ))}
              </div>
            ) : (
              <p data-testid="transcript">{t("media.textLoading")}</p>
            )}
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
            aria-label={playing ? t("player.pause") : t("player.play")}
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
            aria-label={t("player.progress")}
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
            aria-label={t("player.progress")}
            max={view.duration}
            value={view.time}
          />
        )}
        <span data-testid="media-time">
          {formatTime(view.time)} / {formatTime(view.duration)}
        </span>
        <button
          className="media-control-button"
          aria-label={muted ? t("player.unmute") : t("player.mute")}
          title={silentModality ? t("media.noAudio") : undefined}
          disabled={silentModality}
          onClick={() => setMuted((value) => !value)}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <label className="speed-label">
          <select
            aria-label={t("player.rate")}
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
          <button onClick={onReload}>{t("player.reload")}</button>
        </div>
      )}
    </section>
  );
}
