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
