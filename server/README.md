# XMER 标注平台后端（V2）

FastAPI + Postgres，为 V2 云端数据管理提供存储与调度。设计定稿见仓库根目录 `handover.md` 的「V2 设计定稿」一节。

## 目录

```
app/config.py    环境配置、阶段与模态常量
app/db.py        引擎、会话工厂、建表
app/models.py    七张表的数据模型
app/main.py      FastAPI 应用工厂
tests/           pytest
```

## 本地开发

```bash
pip install -r requirements.txt
pytest                       # 用内存 SQLite，无需起数据库
uvicorn app.main:app --reload
```

生产用 Postgres，通过环境变量注入：

```bash
XMER_DATABASE_URL=postgresql+psycopg://user:pass@host/xmer_annotation
XMER_ADMIN_TOKEN=<管理端 token>
```

## 两点说明

**JSON 列**：生产库用 JSONB，测试跑 SQLite 时退回通用 JSON（`models.py` 里的 `JsonCol`）。这样建模型不必依赖本地起一个 Postgres。

**建表方式**：T1 阶段以 SQLAlchemy 模型为唯一真相源，`create_all` 直接建表。上线前（T5）引入 Alembic 管理增量迁移——届时首个 revision 以当前模型为基线。

## 核心不变量

测试重点守住这几条，改动时不要破坏：

- `sample_chunks` 主键 `(attempt_id, chunk_index)` 即幂等键，断网重传不产生重复采样
- 采样块按 `chunk_index` 拼接还原轨迹，允许乱序到达
- 提交走版本链（`previous_submission_id`），Update 不覆盖历史
- `(annotator_id, task_id, revision)` 唯一，挡住重复提交
- `(annotator_id, task_id, phase)` 唯一：同阶段不重复分配，但同一样本可在不同阶段再次出现（P3 锚点复标）

## 管理工具 `manage.py`

```bash
export XMER_DATABASE_URL=postgresql+psycopg://user:pass@host/xmer_annotation

# 1. 批量建账号，导出专属链接（明文 token 只出现这一次）
python manage.py create-annotators --count 20 --phase main --prefix P3 \
    --base-url https://<域名>/annotation --out annotators_P3.csv

# 2. 生成分配计划 CSV（不写库，可用表格软件手改）
python manage.py plan --pool <04>/annotation_pool_3500.jsonl \
    --anchors <04>/anchor_set_500.jsonl --anchor-count 300 \
    --phase main --coverage 2 --out plans/assignment_plan_P3.csv

# 3. 把（可能已手改的）计划写入数据库
python manage.py apply-plan --plan plans/assignment_plan_P3.csv --phase main

# 4. 查看现状
python manage.py status
```

**为什么计划先出 CSV 再回填**：分配是研究设计决策，需要人工复核和手动调整；CSV 可用表格软件直接改，改完 `apply-plan` 覆盖写入。同一 `--seed` 可完整重现一份计划，便于回溯。

**`--coverage` 决定锚点还有没有意义**：锚点的价值在于同一样本被多人标注才能算一致性。`coverage=1` 等于没有重叠，锚点白设。默认 2。

**账号 CSV 含明文 token**，已在 `.gitignore` 中排除；服务器只存哈希，文件丢了只能重新生成账号。
