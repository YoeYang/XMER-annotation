import type { Attempt, Sample } from "../types";

export function normalizeValue(x: number, width: number): number {
  if (!Number.isFinite(x) || !Number.isFinite(width) || width <= 0) return 0;
  return Math.max(-1, Math.min(1, (x / width) * 2 - 1));
}
/**
 * 按**媒体时间**定频采样：每 1/hz 秒的媒体时间记一个点，与播放倍速无关。
 *
 * 不能挂在墙上时钟上。那样 0.5 倍速看同一段素材要花两倍的真实时间，
 * 就会采出两倍的点；不同倍速标出来的曲线时间栅格对不齐，没法逐点比较，
 * 点数也不能再当作标注量的指标。
 *
 * 落点对齐到统一栅格（0.0 / 0.1 / 0.2 …），所有人所有倍速的曲线因此
 * 天然同格，分析时不必重采样。轮询频率取目标频率的 POLL_FACTOR 倍，
 * 保证跨格能被及时发现——真实察觉时刻与栅格时刻的偏差上限是一个轮询周期。
 */
const POLL_FACTOR = 4;

export class Sampler {
  private timer: ReturnType<typeof setInterval> | undefined;
  private lastCell = -1;
  constructor(
    private hz: number,
    private read: () => { time: number; value: number; playing: boolean },
    private record: (time: number, value: number) => void,
  ) {
    if (!Number.isFinite(hz) || hz <= 0) throw new Error("采样频率必须为正数");
  }
  reset() {
    this.stop();
    this.lastCell = -1;
  }
  capture(force = false) {
    const { time, value, playing } = this.read();
    if ((!playing && !force) || !Number.isFinite(time) || time < 0) return;
    const cell = Math.floor(time * this.hz);
    if (cell <= this.lastCell) return;
    this.lastCell = cell;
    this.record(cell / this.hz, value);
  }
  start() {
    if (this.timer !== undefined) return;
    this.capture();
    this.timer = setInterval(
      () => this.capture(),
      1000 / (this.hz * POLL_FACTOR),
    );
  }
  stop() {
    if (this.timer !== undefined) clearInterval(this.timer);
    this.timer = undefined;
  }
}
export function makeSample(
  attempt: Attempt,
  time: number,
  value: number,
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
    value,
    is_valid: true,
  };
}
