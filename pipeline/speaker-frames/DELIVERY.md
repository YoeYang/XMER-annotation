# 说话人静帧 · 交付说明（给 05-annotation）

交付日期 2026-09-12。共 **3440 条**，全部 `status=ok`。

## 文件位置

根目录 `/scratch/project_2017416/yyy2026/XMER/06-speaker-frames/out/`

| 文件 | 说明 |
| --- | --- |
| `manifest.jsonl` | **3440 条交付记录**，每行一条 JSON，导入 `tasks` 表用这个 |
| `frames/<sample_id>.jpg` | 3440 张静帧，512×512，与 manifest 严格一一对应 |
| `discarded.txt` | **60 条剔除清单**（纯 sample_id，每行一个），导入前用它从标注池排除 |
| `discarded.jsonl` | 同上，但带每条的剔除原因，供追溯 |
| `discarded_frames/` | 被剔除样本的静帧，仅作追溯，不要导入 |

## manifest.jsonl 字段

```json
{
  "sample_id": "meld_dia556_utt6",
  "source": "meld",
  "speaker_name": "Ross",              // 无说话人元数据的来源为 null
  "frame_path": "frames/meld_dia556_utt6.jpg",
  "source_time": 1.84,                 // 该帧在原视频中的时刻（秒）
  "bbox": [x, y, w, h],                // 原视频坐标系下的人脸框
  "method": "facelib+gemini",          // 这条是靠什么定下来的
  "confidence": 0.87,
  "status": "ok",                      // 交付集全部为 ok
  "note": "",
  "verify": "yes",                     // 有复核的条目才有，下面三个同理
  "verify_confidence": 0.95,
  "pick_note": "...",                  // 判别阶段模型的原话
  "verify_note": "..."                 // 复核阶段模型的原话
}
```

**注意 `frame_path` 是相对 `out/` 的路径**，不是绝对路径，也不是相对项目根。
拼绝对路径用 `/scratch/project_2017416/yyy2026/XMER/06-speaker-frames/out/` + `frame_path`。

## 导入 tasks 表

`server/app/models.py:66-67` 预留的两个字段直接对应：

| tasks 字段 | 取值 |
| --- | --- |
| `speaker_ref_src` | `frame_path`（转成前端可访问的 URL 或拷贝到静态目录后的路径） |
| `speaker_name` | `speaker_name`（可能为 null，前端要能处理） |

导入前先按 `discarded.txt` 排除那 60 条，`manage.py apply-plan` 的样本数按 **3440** 算。

`speaker_name` 为 null 的情况：chsims（917）、iemocap（874）、mosi（521）这三个来源
本身就没有说话人姓名元数据，**共 2312 条，占交付集的 67%**。
这类样本标注页只展示静帧、不展示姓名，前端必须能处理 null。
有姓名的只有 meld（885）和 mustard（243）共 1128 条。

## 各来源构成

| 来源 | 交付 | 剔除 |
| --- | --- | --- |
| meld | 885 | 35 |
| chsims | 917 | 2 |
| iemocap | 874 | 3 |
| mosi | 521 | 0 |
| mustard | 243 | 20 |
| **合计** | **3440** | **60** |

## 这批图的可信度

| 判据 | 条数 | 说明 |
| --- | --- | --- |
| 人工确认 | 193 | 研究者看视频逐条选定，最可靠 |
| 双判据交叉验证 | 1861 | 人脸库匹配与 Gemini 各自独立判断且结论一致 |
| 本地单判据 | 1395 | iemocap / mosi，画面里自始至终只有一个人，不存在选错的可能 |

被两道判据标为存疑的 248 条已全部经人工复核，其中 47% 确实是机器选错了、已改正。
复核方法与完整结论见 `human-review-report.md`，流水线设计见 `README.md`。

## 已知限制

- **iemocap 874 条的人脸像素偏低**（中位 48px，放大到 512×512 会糊）。保留的理由是它
  单人半身固定机位，轮廓、发型、性别都辨认得出，且画面里没有第二个人可混淆。
  如果标注页觉得糊得影响使用，可以考虑把这批的展示尺寸调小，而不是剔除。
- `speaker_name` 里有少量非人名标签（`PERSON`、`All` 等，来自 mustard 原始元数据），
  前端展示时可考虑过滤掉这类值，只显示静帧。
