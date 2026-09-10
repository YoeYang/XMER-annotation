# XMER 连续情感标注网页

第一版提供本地完整标注流程：样本目录、四种材料类型、Valence／Arousal 二维连续标注、10 Hz 原始媒体时间采样、本地自动保存、Submit／Update、刷新恢复和 JSON 导出。

## 环境与启动

项目使用独立环境 `D:\anaconda\envs\xmer-annotation`。环境内已安装 Node.js 22.23.2、npm 10.9.8 和 FFmpeg 9.0.1；前端依赖位于当前项目的 `node_modules`。

在项目根目录运行：

```powershell
& 'D:\anaconda\Scripts\conda.exe' run --no-capture-output --prefix 'D:\anaconda\envs\xmer-annotation' npm run dev
```

然后访问 `http://127.0.0.1:5173`。第一版数据保存在当前浏览器 IndexedDB 中，清除浏览器站点数据会删除本地记录，请及时使用“导出 JSON”备份。

常用验证命令：

```powershell
& 'D:\anaconda\Scripts\conda.exe' run --no-capture-output --prefix 'D:\anaconda\envs\xmer-annotation' npm test
& 'D:\anaconda\Scripts\conda.exe' run --no-capture-output --prefix 'D:\anaconda\envs\xmer-annotation' npm run build
& 'D:\anaconda\Scripts\conda.exe' run --no-capture-output --prefix 'D:\anaconda\envs\xmer-annotation' npm run test:e2e
```

## 素材配置

样本目录位于 `public/tasks.json`。每项任务至少包括 `task_id`、`media_id`、`source_id`、`title`、`modality`、`src`、`duration`、`target`、`demo` 和 `timeline_origin`。支持的 `modality` 为：

- `visual`：无声音轨的视频；
- `audio`：音频；
- `text`：带时间戳的文本；
- `audiovisual`：带声音的视频。

任务的 `duration` 必须与媒体实际时长一致，误差上限为 0.25 秒；所有同源模态必须使用 `timeline_origin: 0` 并由素材制作阶段保证同一时间尺度。

文本文件示例位于 `public/transcripts/demo.json`。每个句子包含 `start`、`end` 和 `tokens`，每个 token 也包含 `start`、`end` 与 `text`。时间单位为秒，时间段不能重叠。网页根据原生无声媒体播放器的 `currentTime` 逐步显示 token，因此速度与停顿来自预先对齐的时间戳。

`scripts/generate-demo.mjs` 可重新生成 12 秒演示媒体：

```powershell
& 'D:\anaconda\Scripts\conda.exe' run --no-capture-output --prefix 'D:\anaconda\envs\xmer-annotation' node scripts/generate-demo.mjs
```

演示媒体、合成音和示例文本只用于界面与流程测试，不应作为实验材料。

## 数据与状态

每个正式采样点包含任务、标注者、模态、媒体、轮次、样本序号、`media_time`、`wall_time`、Valence、Arousal 和有效性字段。`media_time` 始终读取播放器，不用网页经过时间替代。

播放器结束后生成完成草稿并记录 `completed_at`。首次提交产生 revision 1 和 `submitted_at`；重新标注会创建新的 `attempt_id`，随后 Update 产生新 revision、`updated_at` 和上一版本关系。历史轮次和原始样本不会被覆盖。

刷新时，已完整保存的草稿可以继续 Submit；未完成轮次标记为 `interrupted`，不能提交，但会保留用于追踪和导出。单浏览器同时只允许一个页面编辑该本地数据库。

第二版会用云端实现替换本地存储接口，并加入标注者专属网址、样本分配、云端恢复和管理员管理。
