# 二维标注范式数据存档（2026-09-16）

这批数据是在**二维罗盘**范式下采集的：标注者在一个方形区域里拖动光标，
**一次拖动同时产生 valence 与 arousal 两个值**，存在同一个采样点里。

2026-09-15 之后标注方式将改为**两个一维 bar 分开标注**（按住才采样、松开则媒体暂停、
必须播完整段）。**新旧两种范式的数据不能直接混在一起分析**——二维联合评定与
两次一维评定在认知负荷、维度耦合上不是同一回事。此存档即为改范式前的完整切片。

## 内容

| 文件 | 说明 |
| --- | --- |
| `full_export.json` | 全部 26 个账号的打包导出，服务端 `GET /api/admin/export` 原样落盘 |
| `per-annotator/<ID>.json` | 单人导出，格式与 V1 `ExportData` 一致，`scripts/plot_va_curves.py` 可直接读 |

导出时间 **2026-09-15T21:26:46Z**，来源是阿里云 ECS 上的生产库。

## 数据概况

| 账号 | 阶段 | 提交行数 | 覆盖任务 | 其中更新 | 正式轮次 | 采样点 |
| --- | --- | --- | --- | --- | --- | --- |
| YOE-01 | pilot | 80 | 80 | 0 | 90 | 5436 |
| TR-01 | training | 49 | 40 | 9 | 64 | 3469 |
| TR-02 | training | 42 | 40 | 2 | 66 | 3405 |
| TR-03 | training | 40 | 40 | 0 | 81 | 5582 |
| TR-04 | training | 58 | 40 | 18 | 82 | 5470 |
| SUP-01 | training | 0 | 0 | 0 | 4 | 88 |
| **合计** | | **269** | **240** | **29** | **387** | **23450** |

20 个 P3（main 阶段）账号已分配 15036 条任务但**一条未标**，故无数据。

**「提交行数」与「覆盖任务」不同**：前者含重标后的更新版本，后者是去重的任务数。
管理端进度页显示的是后者。SUP-01（导师）开过 4 个轮次试用但没有提交。

## 采集口径

- **采样频率 10 Hz**，但这批数据里采样是挂在**墙上时钟**上的，所以
  **倍速会改变采样密度**：YOE-01 有 7 个任务用 0.5× 标（约 20.8 点/秒、间隔 0.050s）、
  2 个用 0.75×（13.6 点/秒、0.075s），其余全部 1×（10.6 点/秒、0.100s）。
  TR-01…TR-04 全程 1×。**分析时那 9 个任务需要先降采样到 0.1s 栅格。**
  （2026-09-15 之后采样已改为按媒体时间定频，新数据不再有这个问题。）
- 素材：`visual.mp4` 为 chsims 裁字幕、iemocap 裁黑边之后的版本；四模态共用一条时间轴。
- 样本编号映射见 `server/plans/display_ids.csv`。
- 培训分组见 `server/plans/training_session_groups.csv`：
  TR-01+TR-02 标 A 组 10 个样本，TR-03+TR-04 标 B 组 10 个，加上 YOE-01，
  **每个样本 3 份标注**。

## 校验

导出当时逐项核对过，均为 0 异常：

- 已提交但没有采样点的轮次：0
- 缺维度（valence 或 arousal 为空）的采样点：0
- 媒体时间非单调的轮次：0
- 单人导出与全量导出的提交、轮次集合逐一比对：全部一致

SHA-256（前 16 位）：

```
03a6041037baa200  full_export.json
ec15be7418718b19  per-annotator/SUP-01.json
77d76ec661af878a  per-annotator/TR-01.json
ae52e1bc8069e998  per-annotator/TR-02.json
10b66d19f32fa77d  per-annotator/TR-03.json
6e393f3a3748841e  per-annotator/TR-04.json
eb6a639176ba8c0f  per-annotator/YOE-01.json
```

完整校验和见 `SHA256SUMS`，核对方式：`sha256sum -c SHA256SUMS`。

## 已知的质量问题

首轮质检（见 `handover.md` 的 2026-09-15 一节）发现 **TR-02 与 TR-04 把连续标注
做成了「摆一个点就不动」**：第 1 秒之后效价轨迹中位数 0.002 / 0.003，而 YOE-01 是 0.543。
他们不是敷衍——起手落点各不相同、与 YOE-01 中等相关（r 约 0.5–0.7）、耗时与片长相当，
且在少数任务上跟得很好。**这正是促成改用一维 bar 的原因之一。**

TR-01 与 TR-03 的数据是 2026-09-15 晚补标的，尚未做同样的质检。

## 怎么读

```bash
# 画某个人某个样本的四模态曲线
python scripts/plot_va_curves.py archive/2026-09-16-2d-paradigm/per-annotator/YOE-01.json --out /tmp/plots

# 同一样本多人对照（左效价、右唤醒）
python scripts/plot_annotator_compare.py --sample meld_dia923_utt2 \
  --export "Yoe=archive/2026-09-16-2d-paradigm/per-annotator/YOE-01.json" \
  --export "TR-02=archive/2026-09-16-2d-paradigm/per-annotator/TR-02.json" \
  --out /tmp/plots
```
