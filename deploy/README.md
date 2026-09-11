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

## 建表与 Alembic

容器启动时跑 `create_all`（幂等）。**Alembic 推迟到 P1 pilot 开跑前引入**，理由是现在
库里没有任何真实标注数据，而 T4/T6/T7 还会改 schema，此时写迁移是给会变的表做无用功。

代价要记清楚：**`create_all` 不会 ALTER 已存在的表**。在 P1 之前改了模型，需要手动
drop 掉相关表让它重建；一旦有了真实标注数据，就必须先上 Alembic 再改 schema。

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
