import type { Attempt, Point, Sample } from "../types";
export function normalizePoint(
  x: number,
  y: number,
  width: number,
  height: number,
): Point {
  return {
    valence: Math.max(-1, Math.min(1, (x / width) * 2 - 1)),
    arousal: Math.max(-1, Math.min(1, 1 - (y / height) * 2)),
  };
}
export class Sampler {
  private timer: ReturnType<typeof setInterval> | undefined;
  private lastTime = -1;
  constructor(
    private hz: number,
    private read: () => { time: number; point: Point; playing: boolean },
    private record: (time: number, point: Point) => void,
  ) {
    if (!Number.isFinite(hz) || hz <= 0) throw new Error("采样频率必须为正数");
  }
  reset() {
    this.stop();
    this.lastTime = -1;
  }
  capture() {
    const { time, point, playing } = this.read();
    if (playing && Number.isFinite(time) && time >= 0 && time > this.lastTime) {
      this.record(time, { ...point });
      this.lastTime = time;
    }
  }
  start() {
    if (this.timer !== undefined) return;
    this.capture();
    this.timer = setInterval(() => this.capture(), 1000 / this.hz);
  }
  stop() {
    if (this.timer !== undefined) clearInterval(this.timer);
    this.timer = undefined;
  }
}
export function makeSample(
  attempt: Attempt,
  time: number,
  point: Point,
): Sample {
  return {
    task_id: attempt.task_id,
    annotator_id: attempt.annotator_id,
    modality: attempt.modality,
    media_id: attempt.media_id,
    attempt_id: attempt.attempt_id,
    sample_index: attempt.sample_count,
    media_time: time,
    wall_time: new Date().toISOString(),
    ...point,
    is_valid: true,
  };
}
