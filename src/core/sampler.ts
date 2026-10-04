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
/**
 * 两次轮询之间跳过的格子最多补这么多（2026-10-04）。
 *
 * 主线程一卡，轮询就迟到，媒体时间已经跨过好几格，原来只记当前格、中间的直接丢掉
 * ——10.4 查出 body 缺 37% 的点就是这么来的。卡顿造成的跳格按前后两个实测点线性
 * 补上并标 `filled`；跳得比这还远更像是跳转而不是卡顿，不补。
 */
const MAX_FILL_CELLS = 20;

export class Sampler {
  private timer: ReturnType<typeof setInterval> | undefined;
  private lastCell = -1;
  private lastValue = 0;
  /** 上一格之后一直在连续播放（没暂停、没缓冲、没停过）——只有这样跳格才是卡顿 */
  private continuous = false;
  constructor(
    private hz: number,
    private read: () => { time: number; value: number; playing: boolean },
    private record: (time: number, value: number, filled?: boolean) => void,
  ) {
    if (!Number.isFinite(hz) || hz <= 0) throw new Error("采样频率必须为正数");
  }
  reset() {
    this.stop();
    this.lastCell = -1;
  }
  capture(force = false) {
    const { time, value, playing } = this.read();
    if ((!playing && !force) || !Number.isFinite(time) || time < 0) {
      // 暂停、缓冲、拖动期间媒体时间的跳动不是卡顿，恢复后的第一格不补
      this.continuous = false;
      return;
    }
    const cell = Math.floor(time * this.hz);
    if (cell <= this.lastCell) return;
    const skipped = cell - this.lastCell - 1;
    if (this.continuous && skipped > 0 && skipped <= MAX_FILL_CELLS) {
      const span = cell - this.lastCell;
      for (let c = this.lastCell + 1; c < cell; c++) {
        const share = (c - this.lastCell) / span;
        this.record(c / this.hz, this.lastValue + (value - this.lastValue) * share, true);
      }
    }
    this.lastCell = cell;
    this.lastValue = value;
    this.continuous = playing;
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
    this.continuous = false;
  }
}
export function makeSample(
  attempt: Attempt,
  time: number,
  value: number,
  filled = false,
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
    // 卡顿跳格时按前后实测点线性补的，不是真测到的；分析时可选择剔除
    ...(filled ? { filled: true } : {}),
  };
}
