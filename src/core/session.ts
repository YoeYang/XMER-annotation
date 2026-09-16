import {
  annotationRate,
  rememberAnnotationRate,
  FAMILIARIZATION_RATE,
  HOLD_START_DELAY_MS,
  SAMPLE_RATE_HZ,
} from "../config";
import type {
  Attempt,
  Dimension,
  ExportData,
  Sample,
  SessionView,
  Task,
} from "../types";
import type { AnnotationRepository } from "../storage/repository";
import { makeSample, Sampler } from "./sampler";

export class AnnotationSession {
  view: SessionView;
  private media: HTMLMediaElement | null = null;
  private sampler: Sampler;
  private pending: Sample[] = [];
  private version = 0;
  private savedVersion = 0;
  private saving: Promise<void> | null = null;
  private listeners = new Set<() => void>();
  private detach: (() => void) | null = null;
  private disposed = false;
  private holding = false;
  private holdTimer: ReturnType<typeof setTimeout> | null = null;
  private familiarizationBase = 0;
  private familiarizationLoops = 0;
  private internalSeek = false;
  private preferredRate = annotationRate();

  constructor(
    readonly task: Task,
    readonly annotator: string,
    readonly repository: AnnotationRepository,
  ) {
    this.view = {
      phase: "loading",
      time: 0,
      duration: task.duration,
      rate: FAMILIARIZATION_RATE,
      value: null,
      dimension: null,
      familiarizationPlays: 0,
      attempt: null,
      save: "idle",
      savedAt: null,
      error: null,
      saveError: null,
    };
    this.sampler = new Sampler(
      SAMPLE_RATE_HZ,
      () => ({
        time: this.media?.currentTime ?? 0,
        value: this.view.value ?? 0,
        playing:
          this.holding &&
          this.view.phase === "recording" &&
          !!this.media &&
          !this.media.paused &&
          !this.media.seeking &&
          this.media.readyState >= 3,
      }),
      (time, value) => this.record(time, value),
    );
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private emit() {
    this.view = {
      ...this.view,
      attempt: this.view.attempt ? { ...this.view.attempt } : null,
    };
    this.listeners.forEach((listener) => listener());
  }

  private activeAttempt() {
    return (
      this.view.attempt &&
      ["recording", "paused"].includes(this.view.attempt.status)
    );
  }

  private event(type: string) {
    const attempt = this.view.attempt;
    if (!attempt) return;
    attempt.events.push({
      index: attempt.events.length,
      type,
      media_time: this.media?.currentTime ?? this.view.time,
      wall_time: new Date().toISOString(),
      playback_rate: this.view.rate,
    });
    this.version++;
  }

  private persist() {
    void this.flush().catch(() => {});
  }

  async flush(): Promise<void> {
    if (this.saving) {
      await this.saving;
      if (this.version !== this.savedVersion) await this.flush();
      return;
    }
    if (!this.view.attempt || this.version === this.savedVersion) return;
    const attempt = structuredClone(this.view.attempt);
    const samples = this.pending.slice();
    const version = this.version;
    this.view.save = "saving";
    this.emit();
    this.saving = this.repository
      .checkpoint(attempt, samples)
      .then(() => {
        this.pending.splice(0, samples.length);
        this.savedVersion = version;
        this.view.save = "saved";
        this.view.savedAt = new Date().toISOString();
        this.view.saveError = null;
      })
      .catch((error: unknown) => {
        this.view.save = "error";
        this.view.saveError =
          error instanceof Error ? error.message : "本地保存失败";
        throw error;
      })
      .finally(() => {
        this.saving = null;
        this.emit();
      });
    await this.saving;
    if (this.version !== this.savedVersion) await this.flush();
  }

  attach(media: HTMLMediaElement) {
    this.detach?.();
    this.media = media;
    const events: [string, EventListener][] = [];
    const on = (name: string, listener: () => void) => {
      media.addEventListener(name, listener);
      events.push([name, listener]);
    };
    const ready = () => {
      if (
        !Number.isFinite(media.duration) ||
        media.duration <= 0 ||
        Math.abs(media.duration - this.task.duration) > 0.25
      ) {
        this.fail("媒体时长无效或与任务清单不一致，请检查素材时间轴");
        return;
      }
      this.view.duration = media.duration;
      if (this.view.phase === "loading") this.view.phase = "ready";
      this.emit();
    };
    on("loadedmetadata", ready);
    on("error", () =>
      this.fail("媒体加载失败，请检查文件路径、格式和网络后重新加载"),
    );
    on("playing", () => {
      if (this.disposed) return;
      if (document.hidden) {
        this.releaseHold("page_hidden");
        return;
      }
      if (this.view.dimension === null) {
        this.view.phase = "familiarizing";
        this.emit();
        return;
      }
      if (!this.holding || !this.activeAttempt()) {
        media.pause();
        return;
      }
      this.view.attempt!.status = "recording";
      this.view.phase = "recording";
      this.event("sampling_started");
      this.sampler.start();
      this.emit();
      this.persist();
    });
    on("waiting", () => {
      if (this.view.dimension === null) {
        this.view.phase = "buffering";
      } else if (this.activeAttempt()) {
        this.sampler.stop();
        this.view.phase = "buffering";
        this.event("buffering");
        this.persist();
      }
      this.emit();
    });
    on("pause", () => {
      if (!this.activeAttempt() || media.ended) return;
      this.sampler.stop();
      this.view.attempt!.status = "paused";
      if (this.view.phase !== "hold-delay") this.view.phase = "paused";
      this.emit();
    });
    on("ended", () => {
      if (this.view.dimension === null) {
        this.familiarizationLoops++;
        this.view.familiarizationPlays =
          this.familiarizationBase + this.familiarizationLoops;
        this.view.time = media.duration;
        this.emit();
        if (!this.disposed) {
          media.currentTime = 0;
          void media.play().catch(() => {
            this.view.phase = "ready";
            this.emit();
          });
        }
        return;
      }
      if (!this.activeAttempt()) return;
      this.sampler.capture(true);
      this.sampler.stop();
      this.holding = false;
      this.event("ended");
      this.view.attempt!.status = "completed";
      this.view.attempt!.completed_at = new Date().toISOString();
      this.view.attempt!.last_media_time = media.currentTime;
      this.version++;
      this.view.time = media.currentTime;
      this.view.phase = "completed";
      this.emit();
      this.persist();
    });
    on("seeking", () => {
      this.sampler.stop();
      if (this.internalSeek) return;
      if (this.activeAttempt()) {
        this.interrupt("unexpected_seek");
        this.view.error = "本轮发生跳转，已保留为中断轮次，请重新标注";
        this.emit();
      }
    });
    const visibility = () => {
      if (document.hidden) this.releaseHold("page_hidden");
    };
    document.addEventListener("visibilitychange", visibility);
    const pagehide = () => {
      this.interrupt("page_closed");
      this.persist();
    };
    window.addEventListener("pagehide", pagehide);
    const beforeunload = (event: BeforeUnloadEvent) => {
      if (
        this.activeAttempt() ||
        this.view.save === "error" ||
        this.view.save === "saving"
      ) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeunload);
    const clock = setInterval(() => {
      if (!this.media) return;
      this.view.time = this.media.currentTime;
      if (this.view.dimension === null && this.view.duration > 0) {
        this.view.familiarizationPlays =
          this.familiarizationBase +
          this.familiarizationLoops +
          Math.min(1, this.media.currentTime / this.view.duration);
      }
      this.emit();
    }, 100);
    this.detach = () => {
      events.forEach(([name, listener]) =>
        media.removeEventListener(name, listener),
      );
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", pagehide);
      window.removeEventListener("beforeunload", beforeunload);
      clearInterval(clock);
    };
    if (media.readyState >= 1) ready();
  }

  private async seekToStart() {
    const media = this.media;
    if (!media || media.currentTime === 0) return;
    this.internalSeek = true;
    try {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error("播放器归零超时，请重新加载"));
        }, 5000);
        const finish = () => {
          cleanup();
          resolve();
        };
        const cleanup = () => {
          clearTimeout(timer);
          media.removeEventListener("seeked", finish);
        };
        media.addEventListener("seeked", finish, { once: true });
        media.currentTime = 0;
      });
    } finally {
      this.internalSeek = false;
    }
  }

  async startFamiliarization(): Promise<boolean> {
    if (!this.media || this.disposed || this.view.phase === "error")
      return false;
    this.cancelHoldDelay();
    this.sampler.stop();
    this.media.pause();
    this.view.dimension = null;
    this.view.attempt = null;
    this.view.value = null;
    this.view.rate = FAMILIARIZATION_RATE;
    this.view.error = null;
    this.familiarizationBase = this.view.familiarizationPlays;
    this.familiarizationLoops = 0;
    await this.seekToStart();
    this.media.playbackRate = this.view.rate;
    try {
      await this.media.play();
      return true;
    } catch {
      this.view.phase = "ready";
      this.emit();
      return false;
    }
  }

  async toggleFamiliarization(): Promise<boolean> {
    if (!this.media || this.view.dimension !== null) return false;
    if (!this.media.paused) {
      this.media.pause();
      this.view.phase = "ready";
      this.emit();
      return false;
    }
    try {
      await this.media.play();
      return true;
    } catch {
      this.view.phase = "ready";
      this.emit();
      return false;
    }
  }

  seekFamiliarization(time: number) {
    if (!this.media || this.view.dimension !== null) return;
    this.media.currentTime = Math.max(0, Math.min(time, this.view.duration));
    this.view.time = this.media.currentTime;
    this.emit();
  }

  async finishFamiliarization(): Promise<number> {
    if (!this.media) return this.view.familiarizationPlays;
    const plays =
      this.familiarizationBase +
      this.familiarizationLoops +
      Math.min(1, this.media.currentTime / Math.max(this.view.duration, 1));
    this.view.familiarizationPlays = plays;
    this.media.pause();
    await this.seekToStart();
    this.view.time = 0;
    this.view.phase = "ready";
    this.emit();
    return plays;
  }

  async prepareDimension(dimension: Dimension, familiarizationPlays: number) {
    this.interrupt("dimension_changed");
    await this.flush();
    this.view.attempt = null;
    this.pending = [];
    this.view.dimension = dimension;
    this.view.value = null;
    this.view.rate = this.preferredRate;
    if (this.media) this.media.playbackRate = this.preferredRate;
    this.view.familiarizationPlays = familiarizationPlays;
    this.view.error = null;
    await this.seekToStart();
    this.view.time = 0;
    this.view.phase = "ready";
    this.emit();
  }

  setValue(value: number) {
    this.view.value = Math.max(-1, Math.min(1, value));
    this.emit();
  }

  press(value: number) {
    if (
      !this.media ||
      !this.view.dimension ||
      ["loading", "starting", "error", "completed"].includes(this.view.phase)
    )
      return;
    this.setValue(value);
    this.holding = true;
    this.sampler.stop();
    this.media.pause();
    this.cancelHoldDelay();
    this.holding = true;
    this.view.phase = "hold-delay";
    this.emit();
    this.holdTimer = setTimeout(
      () => void this.beginSampling(),
      HOLD_START_DELAY_MS,
    );
  }

  private async beginSampling() {
    this.holdTimer = null;
    if (!this.holding || !this.media || !this.view.dimension) return;
    if (!this.activeAttempt()) this.createAttempt(this.view.dimension);
    this.media.playbackRate = this.view.rate;
    try {
      await this.media.play();
    } catch {
      this.releaseHold("play_failed");
      this.fail("播放失败，请重新标注或重新加载材料");
    }
  }

  private createAttempt(dimension: Dimension) {
    const now = new Date().toISOString();
    this.view.attempt = {
      schema_version: 1,
      attempt_id: crypto.randomUUID(),
      task_id: this.task.task_id,
      annotator_id: this.annotator,
      media_id: this.task.media_id,
      modality: this.task.modality,
      mode: "annotation",
      dimension,
      familiarization_plays: this.view.familiarizationPlays,
      status: "paused",
      task_snapshot: { ...this.task },
      sample_rate_hz: SAMPLE_RATE_HZ,
      started_at: now,
      completed_at: null,
      sample_count: 0,
      last_media_time: 0,
      events: [],
      calibration: null,
    };
    this.pending = [];
    this.version++;
    this.sampler.reset();
    this.event("attempt_created");
  }

  releaseHold(reason = "pointer_released") {
    const wasDelaying = this.view.phase === "hold-delay";
    this.holding = false;
    this.cancelHoldDelay();
    this.sampler.stop();
    this.media?.pause();
    if (this.activeAttempt()) {
      this.view.attempt!.status = "paused";
      this.view.phase = "paused";
      this.event(reason);
      this.persist();
    } else if (wasDelaying) {
      this.view.phase = "ready";
    }
    this.emit();
  }

  private cancelHoldDelay() {
    if (this.holdTimer) clearTimeout(this.holdTimer);
    this.holdTimer = null;
  }

  private record(time: number, value: number) {
    const attempt = this.view.attempt;
    if (
      !attempt ||
      (attempt.sample_count > 0 && time <= attempt.last_media_time)
    )
      return;
    this.pending.push(makeSample(attempt, time, value));
    attempt.sample_count++;
    attempt.last_media_time = time;
    this.version++;
    this.emit();
    if (attempt.sample_count % SAMPLE_RATE_HZ === 0) this.persist();
  }

  setRate(rate: number) {
    this.view.rate = rate;
    if (this.view.dimension !== null) {
      this.preferredRate = rate;
      rememberAnnotationRate(rate);
    }
    if (this.media) this.media.playbackRate = rate;
    if (this.activeAttempt()) {
      this.event("rate_change");
      this.persist();
    }
    this.emit();
  }

  interrupt(reason = "interrupted") {
    this.holding = false;
    this.cancelHoldDelay();
    this.sampler.stop();
    if (this.activeAttempt()) {
      this.event(reason);
      this.view.attempt!.status = "interrupted";
      this.version++;
    }
    this.media?.pause();
  }

  async resetDimension() {
    const dimension = this.view.dimension;
    const plays = this.view.familiarizationPlays;
    if (!dimension) return;
    await this.prepareDimension(dimension, plays);
  }

  fail(message: string) {
    this.interrupt("media_error");
    this.view.phase = "error";
    this.view.error = message;
    this.emit();
    this.persist();
  }

  async exportData(): Promise<ExportData> {
    let unsaved = false;
    try {
      await this.flush();
    } catch {
      unsaved = true;
    }
    const data = await this.repository.export(this.annotator);
    if (unsaved && this.view.attempt) {
      const id = this.view.attempt.attempt_id;
      const persisted = data.attempts.find(
        (attempt) => attempt.attempt_id === id,
      );
      const samples = new Map(
        (persisted?.samples ?? []).map((sample) => [
          sample.sample_index,
          sample,
        ]),
      );
      for (const sample of this.pending)
        samples.set(sample.sample_index, sample);
      data.attempts = data.attempts.filter(
        (attempt) => attempt.attempt_id !== id,
      );
      data.attempts.push({
        ...structuredClone(this.view.attempt),
        samples: [...samples.values()].sort(
          (a, b) => a.sample_index - b.sample_index,
        ),
      });
      data.unsaved_attempt_ids.push(id);
    }
    return data;
  }

  async leave() {
    if (this.view.phase === "starting")
      throw new Error("播放器正在开始，请稍后再切换任务");
    this.interrupt("task_left");
    await this.flush();
  }

  dispose() {
    this.disposed = true;
    this.interrupt("view_closed");
    this.persist();
    this.detach?.();
    this.detach = null;
    this.listeners.clear();
  }
}
