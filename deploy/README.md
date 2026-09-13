# T5 部署记录（阿里云 ECS）

复用 04 的香港 ECS `47.238.255.165`，与 Label Studio / training 页共存，互不干扰。
栈目录 `/opt/xmer-label/`，SSH：`ssh -i ~/.ssh/xmer_ecs root@47.238.255.165`。

## 拓扑

```
Caddy :443
 ├── /annotation/api/*  → backend:8000   （V2 标注 API，本次新增）
 ├── /annotation*       → /annotation-static  静态 SPA
 ├── /training*         → /label-studio-static
 └── /                  → labelstudio:8080
Postgres（同一容器，两个库互不相干）
 ├── labelstudio
 └── xmer_annotation    （本次新增，owner = xmer）
```

## ⚠️ Caddy 路由顺序不能改

`handle /annotation/api/*` **必须排在 `handle_path /annotation*` 之前**，否则请求会被
静态 `file_server` 吃掉并返回 404。用 `uri strip_prefix /annotation` 而不是
`handle_path`，因为只能剥掉 `/annotation`，剩下的 `/api/...` 正好对上 FastAPI 的路由前缀。

**Caddyfile 是 bind mount，改文件不会自动生效**，必须显式重载：

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

踩过一次：`docker compose up -d caddy` 对纯配置改动是 no-op，容器不重建，内存里还是旧路由。

## 配置与密钥

`/opt/xmer-label/.env.annotation`（chmod 600，**不在 git 里**）：

```
XMER_DB_PASSWORD=…
XMER_ADMIN_TOKEN=…
XMER_DATABASE_URL=postgresql+psycopg://xmer:…@db:5432/xmer_annotation
```

compose 用 `env_file:` 直接喂给容器，**不做变量插值**。这样裸跑 `docker compose up -d`
也不会因为少带 `--env-file` 而把变量变成空串。

配套地，`load_settings()` 在缺 `XMER_DATABASE_URL` 时**直接抛错**而不是回落 SQLite——
这个服务会写标注数据和建账号，"不知道自己在写哪个库"比起不来危险得多。

## 表结构与迁移（Alembic）

**表结构一律走 Alembic，`create_all` 已从启动路径移除。** 容器启动命令是
`alembic upgrade head && uvicorn ...`，迁移脚本在 `server/migrations/`。

基准版本 **`a5434311ec63`**（2026-09-13 建立，对应 V2 的七张表）。生产库原本的表是
`create_all` 建的，Alembic 并不知道它们存在，因此上线时先 `stamp` 标记、不重建：

```bash
docker compose build backend
docker compose run --rm backend alembic stamp head   # 只有首次接管时需要
docker compose up -d backend
```

**为什么必须用它**：`create_all` 只建不存在的表，永远不会 ALTER。改了模型之后新库看着正常，
线上老表却没有新列，唯一补救是 drop 重建 = 真实标注数据全没。

**改了 `app/models.py` 之后必须生成迁移**：

```bash
XMER_DATABASE_URL=sqlite+pysqlite:///tmp.db python3 -m alembic revision --autogenerate -m "说明"
```

`tests/test_migrations.py` 会拦住"改了模型忘记生成迁移"——它在空库上跑完全部迁移，
再与模型比对，有差异就失败。

**JSON 列的渲染**由 `migrations/env.py` 的 `render_item` 钩子指向 `app.models.JsonCol`。
没有它，autogenerate 会输出缺 `sa.` 前缀的 `Text()`，生成的脚本一跑就 NameError——
每次碰到 JSON 列都会重犯，所以修在钩子里而不是手改生成的文件。

**Alembic 只管表的形状，不管表里的数据。** 重新分配样本、替换标注结果、调整队列
都走应用层（`manage.py apply-plan` 或管理端接口），与迁移无关。

## 备份

`/opt/xmer-label/backup-annotation.sh`，cron 每日 03:30，保留 14 天，产物在 `backups/`。
脚本会检查转储非空才做轮换，避免一次失败的备份把好备份删掉。

## 更新后端

```bash
rsync -az --delete --exclude __pycache__ --exclude .pytest_cache --exclude '*.db' \
  -e "ssh -i ~/.ssh/xmer_ecs" server/ root@47.238.255.165:/opt/xmer-label/annotation-server/
ssh -i ~/.ssh/xmer_ecs root@47.238.255.165 \
  'cd /opt/xmer-label && docker compose up -d --build backend'
```

## 更新前端静态页

ECS 上没常驻 Node，用一次性容器构建（沿用 2026-09-10 的做法）：

```bash
docker run --rm -v /opt/xmer-annotation-src:/src -w /src node:20-alpine \
  sh -c "npm ci && npm run build"
```

同一个容器也能跑前端测试，Roihu 上没有 node 不构成阻碍：

```bash
docker run --rm -v /opt/xmer-annotation-src:/src -w /src node:20-alpine \
  sh -c "npm ci && npm test && npx tsc --noEmit"
```

## 回滚

改动前的配置已备份为 `docker-compose.yml.bak-t5`、`Caddyfile.bak-t5`。

## 验证过的端点

| 路径 | 期望 |
| --- | --- |
| `/annotation/api/health` | 200 `{"status":"ok","version":"2.0.0"}` |
| `/annotation/api/me` 无令牌 | 401 + 中文提示 |
| `/annotation/api/me` 真令牌 | 200，返回身份与任务队列 |
| `/annotation/`、`/annotation/tasks.json` | 200（未受影响） |
| `/training/` | 200（未受影响） |
| `/` | 302（Label Studio，未受影响） |

## 管理端（T6）

- 页面：`https://47.238.255.165.nip.io/annotation/api/admin/ui`
- 令牌：服务器上 `. /opt/xmer-label/.env.annotation && echo $XMER_ADMIN_TOKEN`

页面本身不鉴权（只是个空壳），令牌在页面里填、存 sessionStorage；**所有数据请求都走
带 `require_admin` 的接口**。令牌比较用 `secrets.compare_digest`，避免用响应时间试出令牌。
服务器未配 `XMER_ADMIN_TOKEN` 时管理端返回 503（整体关闭），而不是放行。

**下一步加固**：Caddy 层给 `/annotation/api/admin/*` 加 IP 白名单作为第二道防线。
本次未加，以免把自己锁在外面——加之前先确认固定出口 IP。
