# CPM标注 · 本地模拟原型

独立于正在进行的 **VA标注**。前端、服务、数据库、构建产物和浏览器草稿均独立。未修改 VA 的 `src/`、`server/`、现有 Vite 配置或部署脚本；没有连接生产数据库。

## 启动

从项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File cpm/start.ps1
```

打开 <http://127.0.0.1:5180/>。脚本只启动 CPM，端口已占用时退出并保留现有进程；控制台输出两个进程 PID，按需使用 `Stop-Process -Id <PID>` 停止它们。API 只监听 `127.0.0.1:5181`。日志位于 `cpm/*.log`。

专用环境：`D:\anaconda\envs\xmer-annotation`，Node.js **22.23.2**、Python **3.14.7**。复用本项目本地 React/Vite 依赖；Python 服务只使用标准库，没有安装全局依赖。

## 已实现

- 360 个模拟样本，三种虚构情境循环组成。CPM-01 / CPM-02 各有同一批 360 条任务，共 720 条；右上角切换演示身份。
- 四步标注：场景核对、R/I/C/N 五档或信息不足、冲突及通道证据、动态变化与可选变化后评分。
- 播放器复用本地合成媒体，仅用于试用播放与媒体时间定位，**画面不对应虚构情境**。未接真实人物媒体；面部/身体单独视图尚未接入。
- 每次编辑暂存独立浏览器草稿；“保存草稿”存入 SQLite。提交服务端校验必填项、依据和时间区间。
- 原始卡片保存于样本表；候选冲突窗口来源固定且不可覆盖，人工核对窗口单独保存；数值 0 与未知 `null` 分开。
- 两位标注者答案分别存储；每次保存追加版本，已提交记录的修订需要原因。当前完成进度按最新保存状态计算；修订为草稿时该任务退回草稿状态，历史提交保留。
- 管理页提供样本搜索、状态筛选、分页、双人进度、最近保存版本，以及完整 JSON 导出（含所有版本）。

## 数据管理

数据库：`cpm/data/cpm-demo.sqlite3`（不进入 Git）。表：

| 表 | 用途 |
| --- | --- |
| samples | 片段 ID、子集、原始事实卡、时长、来源、`va_clip_id`、`selection_metadata` |
| assignments | 两位标注者独立任务；唯一约束 `(clip_id, annotator_id)` |
| records | 任务编号、尝试/保存版本号、量表版本、状态、完整结构化快照、UTC 时间 |

未来可将从 VA 结果筛选的 300–400 条样本作为新的冻结子集导入，使用 `va_clip_id` 和筛选元数据追溯来源。**本次仅预留字段，没有实现真实清单导入或 VA 筛选计算**。两位标注者的原始记录不做聚合覆盖。

当前只有本机模拟身份切换，没有正式账号认证。候选量表 `cpm-2026-10-05-v1-candidate` 尚未冻结。LLM 解释生成/审核仅预留状态字段，未调用模型。这个原型不直接用于正式多人线上采集。

## 验证

```powershell
& 'D:\anaconda\envs\xmer-annotation\python.exe' -m unittest discover -s cpm -p test_server.py -v
& 'D:\anaconda\envs\xmer-annotation\node.exe' node_modules/typescript/bin/tsc -p cpm/tsconfig.json
& 'D:\anaconda\envs\xmer-annotation\node.exe' node_modules/vite/bin/vite.js build --config cpm/vite.config.ts
# 先启动 5180 预览；浏览器测试使用本机 Edge 和独立临时数据库（API 5183）。
& 'D:\anaconda\envs\xmer-annotation\node.exe' cpm/smoke.mjs
```

构建产物仅写到 `cpm/dist/`。浏览器截图位于 `artifacts/cpm-*.png`；测试数据库位于 `cpm/data/browser-test-*/`，不污染示意页面数据库。
