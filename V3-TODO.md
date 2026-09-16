# V3 标注范式改版 · 待办清单

> 方案定稿见 `handover.md` 末节「2026-09-16 续三 · V3 范式定稿」。
> 本文件只管**做什么、做到哪了**；**为什么这么定**一律去 handover 查。
> 完成一项就勾上，并在 handover 里补一条当日记录。

**状态**：全部岔路已决议，无阻塞项。**轨道 A 优先起跑**（周期最长且零依赖）。

## 轨道划分

| | 轨道 A · 数据准备 | 轨道 B · 标注页面 | 轨道 C · 汇合 |
| --- | --- | --- | --- |
| 动哪 | `pipeline/` | `src/` + `server/` | `server/plans/` |
| 依赖 | 无 | 无 | A4 + B1 |
| 可并行 | ✅ 与 B 完全隔离 | ✅ 与 A 完全隔离 | ❌ 需等 A、B |

---

# 轨道 A · 数据准备（visual → face + body）

**目标**：把 `visual.mp4` 拆成 `face.mp4`（裁出说话人脸）与 `body.mp4`（遮住说话人脸），
并处理抽不出脸而必须 drop 的样本。

**已有的底子**（别重造）：
- `06-speaker-frames/out/manifest.jsonl` —— 3440 条，**说话人身份已解决**，
  带 `speaker_name` / `bbox` / `source_time` / `method`（含 `human` 人工核对态）/ `status`
- `discarded.txt` —— 已人工剔除 60 条
- `pipeline/speaker-frames/src/facelib.py` —— YuNet 检测 + SFace 识别，一套依赖
- `pipeline/speaker-frames/src/lipstrip.py` —— 已有稀疏多帧扫描结果，可当轨迹种子

**差距**：现有只是**单个时间点的一个 bbox**；face/body 需要**整段逐帧人脸轨迹**。

## A1 · 人脸轨迹
- [ ] 从 `manifest.jsonl` 的单时点 bbox 出发，扩成整段轨迹：检测 → 跟踪 → 时域平滑 → 丢帧插值
- [ ] 处理说话人转头 / 出画 / 被遮挡
- [ ] 处理 iemocap 双人同框（靠 SFace 身份匹配锁定说话人）
- [ ] 输出轨迹文件（每样本一条，逐帧 bbox）+ 置信度，供 A3 审核挑出低置信样本

## A2 · 两路素材
- [ ] `face.mp4`：按轨迹裁剪。**出画策略待定**（冻结最后一帧 / 黑屏 / 该样本直接 drop）
- [ ] `body.mp4`：按轨迹逐帧遮脸。**建议纯色块，不要高斯模糊**——模糊仍泄露表情强度
- [ ] 确认接在 `recrop_visual.py` **之后**（chsims 裁硬字幕、iemocap 裁黑边已做过）
- [ ] 注意 ffmpeg 有两个，只有 `python-data/3.12-20.04` 自带的 8.0.1 带 libx264；
      spack 的 `ffmpeg/7.1` 不带，`-crf` 会报错。**加载顺序决定用哪个**
- [ ] 注意计算分区 x86 / 登录节点与 GPU 分区 ARM，要 torch 的活投 `gpumedium`

## A3 · 人工审核 + 备份池
- [ ] 复用 `build_gallery.py` / `build_review.py` 的模式做核对页（face 裁剪框 + body 遮挡效果）
- [ ] **939 备份池与主池一起跑完 A1+A2**，一并进审核队列
- [ ] Yoe 人工筛选 → 出 **drop 清单** + **补位清单**

## A4 · 收尾交接
- [ ] 编号处理：drop 样本标 `retired`（**号不回收，留空洞**）；
      备份池样本从 **`S3441`** 起发新号。**`display_ids.csv` 绝不重新生成**
- [ ] 重生成 `tasks_import.json`（5 模态）
- [ ] 跑 `manage.py set-durations --file <{task_id: 秒数}.json>`
      —— 新素材时长变了，前端 **0.25s 容差**会直接拒绝打开任务
- [ ] 更新 `pipeline/README.md`（新增 face/body 步骤）
- [ ] 交接物给轨道 C：`tasks_import.json` + drop 清单 + 时长表

---

# 轨道 B · 标注页面

## B1 · 后端与数据模型
- [ ] `Modality` 改 5 值：`audio` / `text` / `face` / `body` / `audiovisual`，**去掉 `visual`**
- [ ] `Attempt` 加 `dimension`（`valence` / `arousal`）
- [ ] `Attempt` 加熟悉页**真实播放次数**（质检信号：跳太快的人质量单独看）
- [ ] 新 Alembic 迁移（当前 head `22a6741867d8`）
- [ ] 「完成」判定改为**两维轮次齐全**才算完成
- [ ] **读取层「取最新」语义**：`(task, annotator, dimension)` 取最新 Attempt
      —— 界面上是覆盖，库里 append-only 留底
- [ ] `manage.py purge-superseded --keep 3`：**只清 `SampleChunk`**，
      保留 `Attempt` / `Submission` 元数据行（版本链 FK + 重标次数）；
      可顺带置空老轮次的 `task_snapshot`
- [ ] `allocation.py`：计划粒度**样本 → 子任务**，计划 CSV 加 `modality` 列（17,200 行）
- [ ] `manage.py plan` 新增 `--per-annotator`（每人子任务数）
- [ ] `manage.py plan` 新增 `--isolation strict|off`（strict = 同一人不重复见同一样本）
- [ ] `api.py` / `schemas.py` 跟进
- [ ] 导出永远同时带 `task_id` + `source_id` + `display_id` **三样**

## B2 · 前端三页流程
- [ ] `AnnotationPad.tsx` **重写**：二维罗盘 → 一维横条渐变 bar；
      两端写死语义（效价 负向 −1 ←→ 正向 +1；唤醒 冷静 −1 ←→ 激动 +1）；
      当前维**发光**，另一维**纯灰占位且不显示数值**
- [ ] 三页状态机：熟悉页 → valence 页 → arousal 页
- [ ] 熟悉页：自动播 **2 遍**，可继续重复，也可随时「已看懂，下一步」；**上报真实播放次数**
- [ ] `session.ts`：**按住才采样，松手即暂停媒体**
- [ ] `session.ts`：按下后 **0.5s 延迟，期间媒体也停**（甲方案，保住无空洞）；
      **每次按下都罚**；常量抽出来留调节口，试标后再定要不要缩短
- [ ] bar 上方状态条：【采样中…】/【暂停采样…】
- [ ] 四按键布局：**下一步（最大 + 回车）**、标注 bar（鼠标常驻）、
      重新标注（**仅当前维**，另开轮次）、上一步
- [ ] `TaskSidebar.tsx`：子任务 section 分块 + **块内序号**（「面部 3/20」）；
      **不显示样本编号**；块内序号是前端纯函数，**绝不落库**
- [ ] 报障入口显示内部工单号 `<annotator_id>-<modality>-<块内序号>`（如 `P3-07-face-03`）
- [ ] 切换模态时弹指引提示
- [ ] `config.ts`：倍速表改 `[0.1, 0.5, 1]`，**默认 0.5**
- [ ] `config.ts`：**音频子任务 0.1× 给小警告**（已知坑：音频在 0.1× 下基本听不清）

## B3 · 测试
- [ ] `sampler` / `session`：按住语义、0.5s 延迟、**无空洞断言**
      （注意：边界值测试要避开被测逻辑的分界点，别让媒体时间正好停在格点上）
- [ ] `repository`：三页流程下的草稿与中断恢复
- [ ] 后端 99 个：跟进 5 模态 + 维度轮次 + 新分配 + purge
- [ ] e2e 14 个：基本重写（三页流程、模态分块、回车导航）
- [ ] `plot_va_curves.py` / `plot_annotator_compare.py`：适配「一个子任务只有一维」

---

# 轨道 C · 汇合（等 A4 + B1）

- [ ] 按缩水后的池子重排分配计划（**子任务粒度**、硬隔离、`--per-annotator`）
- [ ] 锚点集 318 重新散布（原池子基于 3440）
- [ ] 选定 **3 个校准样本**：候选排序**不变**，但 reference 须用新范式**重标**
- [ ] 更新 `handover.md`

---

# 悬着的账（非编码）

- [ ] **工作量要和导师算**：约 17,200 子任务、每人约 940 个、
      0.5× 下**每人 9.6 小时纯播放**。最大放大器是默认 0.5×。
      减负杠杆：削样本量 / 削模态 / 削冗余（3 份 → 2 份）/ 默认倍速调 1×。
      详见 handover 定稿第五节
- [ ] **GitHub token 建议 revoke**（协作中多次明文传递过）
- [ ] `04-conflict-sampling` 仍未纳入 git，内有明文 `OPENAI_KEY.txt`，建议先轮换
- [ ] 大文件清理：`08/out/visual-backup/` 2.6G、`07/models/hub` 2.8G、顶层 01/02/03 865M
