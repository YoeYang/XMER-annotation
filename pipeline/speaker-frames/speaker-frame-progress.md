# 说话人静帧预处理 · 进度

最后更新：2026-09-12（人工复核已完成，任务收尾）。设计与实现说明见 `README.md`，这里只记状态和待办。

## 状态：已完成

人工复核已完成，**交付集 3440 条，全部 status=ok**，剔除 60 条。
复核结论与数据见 `human-review-report.md`。

| 来源 | 交付 | 剔除 |
| --- | --- | --- |
| meld | 885 | 35 |
| chsims | 917 | 2 |
| iemocap | 874 | 3 |
| mosi | 521 | 0 |
| mustard | 243 | 20 |
| **合计** | **3440** | **60** |

判据构成：人工确认 193 条、双判据交叉验证 1861 条、本地单判据 1395 条（iemocap/mosi，
画面单人不存在选错的可能）。累计 API 成本约 $3.0。

## 交付物

```
out/frames/<sample_id>.jpg     3440 张说话人静帧
out/manifest.jsonl             3440 条，下游契约
out/discarded.jsonl / .txt     60 条剔除清单（含原因），供 05 从标注池排除
out/speaker_picks.json         人工复核原始记录（不可再生，勿删）
README.md                      设计与实现说明
human-review-report.md         人工复核结论
speaker-frame-progress.md      本文件
src/                           全部代码
```

## 接手须知

```bash
export GEMINI_API_KEY=...        # 只从环境变量读，代码里没有
./run.sh report                  # 先看当前状态
```

每一步都可断点续跑，重跑自动跳过已完成的样本，直接接着跑就行。
中间产物 `facescan.jsonl`（人脸扫描，跑一次 45 分钟）和 `embeds.npz` / `gallery.npz`
（角色人脸库）都已落盘，不用重跑。

环境：`module load` 必须写成 `bash -lc 'module load X; cmd'`，
非交互 shell 里直接 `module load` 后 PATH 不生效。

## 一个教训，别再犯

我曾经拿**单帧**标注图判断「谁在张嘴」，据此向 Yoe 汇报「chsims 抽验 8/8 全对」。
后来第二道判据翻出其中一条是错的（`chsims_aqgy3_0001_00016`），拉出唇部序列一看，
我选中的人全程基本闭嘴、旁边那个才在连续开合。

**单帧判断不了谁在说话**：说话的人可能恰好闭嘴，没说话的人可能因表情恰好张嘴。
`src/lipstrip.py` 就是为此写的，验证唇动一律用它。

同理，**复核必须换一种问法才有意义**。判别阶段问「从编号框里选一个」是多选一、模型会硬选；
复核阶段问「是不是这个人」是二元验证、答不上来可以说 no。
就是这个差异在 meld/mustard 上翻出 137 条自我矛盾、在 chsims 上翻出 47 条。

## 交付给 05-annotation

`tasks` 表的 `speaker_ref_src` 与 `speaker_name` 两个字段已核对，类型对得上
（`server/app/models.py:66-67`，都是 `Text`），直接取 manifest 的 `frame_path` 和 `speaker_name`。
注意 `frame_path` 是相对 `out/` 的路径（如 `frames/meld_dia11_utt9.jpg`），
转成前端可访问的 URL 是素材导入那边的事，06 不碰 05 的代码。

T4 开发要的示例样本 `meld_dia11_utt9` 已在产出里，不必再手工截图。
