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
- `(annotator_id, task_id, phase)` 唯一：同阶段不重复分配；同一账号可同时挂 training 与 main 两批

## 管理工具 `manage.py`（2026-09-29 版）

```bash
export XMER_DATABASE_URL=postgresql+psycopg://user:pass@host/xmer_annotation

# 1. 建正式账号：编号 P<阶段>-<ZH|EN>-<序号>，phase=main，号只发不收
python manage.py create-annotators --stage 1 --language zh --count 2 \
    --base-url https://<域名>/annotation --out p1_zh.csv
python manage.py create-annotators --stage 1 --language en --count 6 \
    --base-url https://<域名>/annotation --out p1_en.csv

# 2. 按语言挂训练分配（照抄 TRZH-01 / TREN-01）；训练交齐后自动解锁正式任务
python manage.py assign-training --stage 1

# 3. 生成分配计划 CSV（不写库）。按编号前缀 P1- 取人
python manage.py plan --pool plans/pool_3420.jsonl --stage 1 --coverage 2 \
    --seed 20260929 --out plans/assignment_plan_P1.csv

# 4. 写入数据库（任何一人已开工就整份拒绝，开工后只能释放与转移）
python manage.py apply-plan --plan plans/assignment_plan_P1.csv --phase main

# 5. 查看现状
python manage.py status
```

**为什么计划先出 CSV 再回填**：分配是研究设计决策，需要人工复核；同一 `--seed` 可完整重现一份计划，便于回溯。

**分配规则**：唯一重复约束是同一人不拿两次相同的 (样本, 模态)；chsims 的 text/full 只给中文标注者；
中文标注者另拿非 chsims 的 text/full 各 `--zh-open-quota` 条（默认 300）。细节见 `app/allocation.py` 模块说明。

**账号 CSV 含明文 token**，已在 `.gitignore` 中排除；服务器只存哈希，文件丢了只能重新生成账号。

## 端到端测试

需要一个**独立于正式账号**的测试标注者——e2e 会真的写入轮次和提交，混进正式数据里
就再也分不清哪些是人标的。

```bash
# 1. 造号并分配一个样本，命令输出即令牌
TOK=$(docker compose exec -T backend python manage.py seed-e2e | tail -1)

# 2. 跑（镜像版本必须与 package.json 里的 @playwright/test 一致，否则浏览器二进制对不上）
#    ECS 上不常驻前端源码（9.30 起），先把仓库 rsync 到 /opt/xmer-annotation-src，跑完删掉
docker run --rm --network host -v /opt/xmer-annotation-src:/src -w /src \
  -e E2E_BASE_URL=https://<域名> -e E2E_TOKEN="$TOK" \
  mcr.microsoft.com/playwright:v1.63.0-noble \
  sh -c "npm ci && npx playwright test"

# 3. 收尾：连同它产生的全部数据一起删掉
docker compose exec -T backend python manage.py drop-annotator --annotator-id E2E-TEST
```

不设 `E2E_BASE_URL` 时会本地拉起 vite；此时需要 `VITE_API_TARGET` 指向后端。
