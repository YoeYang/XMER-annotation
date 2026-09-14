import { rememberedRate, rememberRate, SAMPLE_RATE_HZ } from "../config";
import type {
  Attempt,
  ExportData,
  Point,
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
  constructor(
    readonly task: Task,
    readonly annotator: string,
    readonly repository: AnnotationRepository,
  ) {
    this.view = {
      phase: "loading",
      time: 0,
      duration: task.duration,
      rate: rememberedRate(),
      point: null,
      attempt: null,
      curve: [],
      save: "idle",
      savedAt: null,
      error: null,
      saveError: null,
    };
    this.sampler = new Sampler(
      SAMPLE_RATE_HZ,
      () => ({
        time: this.media?.currentTime ?? 0,
        point: this.view.point ?? { valence: 0, arousal: 0 },
        playing:
          this.view.phase === "recording" &&
          !!this.media &&
          !this.media.paused &&
          !this.media.seeking &&
          this.media.readyState >= 3,
      }),
      (time, point) => this.record(time, point),
    );
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private emit() {
    this.view = {
      ...this.view,
      attempt: this.view.attempt ? { ...this.view.attempt } : null,
    };
    this.listeners.forEach((fn) => fn());
  }
  private active() {
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
    const attempt = structuredClone(this.view.attempt),
      samples = this.pending.slice(),
      version = this.version;
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
    const on = (name: string, fn: () => void) => {
      media.addEventListener(name, fn);
      events.push([name, fn]);
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
      if (this.disposed || !this.active()) return;
      if (document.hidden) {
        this.pause("page_hidden");
        return;
      }
      this.view.attempt!.status = "recording";
      this.view.phase =
        this.view.attempt!.mode === "annotation" ? "recording" : "preview";
      this.event("playing");
      this.sampler.start();
      this.emit();
      this.persist();
    });
    on("waiting", () => {
      if (!this.active()) return;
      this.sampler.stop();
      this.view.phase = "buffering";
      this.event("buffering");
      this.emit();
      this.persist();
    });
    on("pause", () => {
      if (!this.active() || media.ended || this.view.phase === "starting")
        return;
      this.sampler.stop();
      this.view.attempt!.status = "paused";
      this.view.phase = "paused";
      this.event("pause");
      this.emit();
      this.persist();
    });
    on("ended", () => {
      if (!this.active()) return;
      this.sampler.stop();
      if (this.view.attempt!.mode === "annotation" && this.view.point)
        this.record(media.currentTime, this.view.point);
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
      if (this.active() && this.view.phase !== "starting") {
        this.interrupt("unexpected_seek");
        this.view.error = "本轮发生跳转，已保留为中断轮次，请重新标注";
        this.emit();
      }
    });
    const visibility = () => {
      if (document.hidden && this.active()) this.pause("page_hidden");
    };
    document.addEventListener("visibilitychange", visibility);
    const pagehide = () => {
      this.interrupt("page_closed");
      this.persist();
    };
    window.addEventListener("pagehide", pagehide);
    const beforeunload = (event: BeforeUnloadEvent) => {
      if (
        this.active() ||
        this.view.save === "error" ||
        this.view.save === "saving"
      ) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeunload);
    const clock = setInterval(() => {
      if (this.active()) {
        this.view.time = media.currentTime;
        this.emit();
      }
    }, 100);
    this.detach = () => {
      events.forEach(([name, fn]) => media.removeEventListener(name, fn));
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", pagehide);
      window.removeEventListener("beforeunload", beforeunload);
      clearInterval(clock);
    };
    if (media.readyState >= 1) ready();
  }
  setPoint(point: Point) {
    this.view.point = point;
    this.emit();
  }
  private record(time: number, point: Point) {
    const attempt = this.view.attempt;
    if (
      !attempt ||
      attempt.mode !== "annotation" ||
      (attempt.sample_count > 0 && time <= attempt.last_media_time)
    )
      return;
    const sample = makeSample(attempt, time, point);
    this.pending.push(sample);
    // pending 会在落盘后清空，曲线要另存一份才画得出来
    this.view.curve.push(sample);
    attempt.sample_count++;
    attempt.last_media_time = time;
    this.version++;
    this.emit();
    if (attempt.sample_count % SAMPLE_RATE_HZ === 0) this.persist();
  }
  async start(mode: "preview" | "annotation", point?: Point) {
    const media = this.media;
    if (
      !media ||
      this.disposed ||
      ["loading", "starting", "error"].includes(this.view.phase)
    )
      return;
    if (
      mode === "annotation" &&
      this.active() &&
      this.view.attempt!.mode === "annotation"
    )
      return;
    this.interrupt("replaced_by_new_attempt");
    this.view.phase = "starting";
    this.view.error = null;
    if (point) this.view.point = point;
    this.emit();
    try {
      await this.flush();
      if (this.disposed) return;
      if (media.currentTime !== 0) {
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
      }
      const now = new Date().toISOString();
      this.view.attempt = {
        schema_version: 1,
        attempt_id: crypto.randomUUID(),
        task_id: this.task.task_id,
        annotator_id: this.annotator,
        media_id: this.task.media_id,
        modality: this.task.modality,
        mode,
        status: "recording",
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
      this.view.curve = [];
      this.version++;
      this.sampler.reset();
      this.view.time = media.currentTime;
      this.event("start");
      if (mode === "annotation" && this.view.point)
        this.record(media.currentTime, this.view.point);
      media.playbackRate = this.view.rate;
      await media.play();
      this.persist();
      this.emit();
    } catch (error) {
      this.fail(error instanceof Error ? error.message : "无法开始播放");
    }
  }
  pause(reason = "user_pause") {
    if (!this.media || !this.active()) return;
    this.sampler.stop();
    this.media.pause();
    this.view.attempt!.status = "paused";
    this.view.phase = "paused";
    this.event(reason);
    this.emit();
    this.persist();
  }
  async resume() {
    if (
      !this.media ||
      !this.active() ||
      !["paused", "buffering"].includes(this.view.phase)
    )
      return;
    try {
      await this.media.play();
    } catch {
      this.fail("播放失败，请重新标注或重新加载材料");
    }
  }
  setRate(rate: number) {
    this.view.rate = rate;
    rememberRate(rate);
    if (this.media) this.media.playbackRate = rate;
    if (this.active()) {
      this.event("rate_change");
      this.persist();
    }
    this.emit();
  }
  interrupt(reason = "interrupted") {
    this.sampler.stop();
    if (this.active()) {
      this.event(reason);
      this.view.attempt!.status = "interrupted";
      this.version++;
    }
    this.media?.pause();
  }
  async reset() {
    this.interrupt("restart");
    await this.flush();
    this.view.attempt = null;
    this.view.point = null;
    this.view.phase = "ready";
    this.view.error = null;
    if (this.media) this.media.currentTime = 0;
    this.view.time = 0;
    this.emit();
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
      const persisted = data.attempts.find((a) => a.attempt_id === id);
      const samples = new Map(
        (persisted?.samples ?? []).map((s) => [s.sample_index, s]),
      );
      for (const sample of this.pending)
        samples.set(sample.sample_index, sample);
      data.attempts = data.attempts.filter((a) => a.attempt_id !== id);
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
      throw new Error("播放器正在开始，请稍后再切换样本");
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
