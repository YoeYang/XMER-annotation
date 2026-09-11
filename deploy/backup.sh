#!/bin/sh
# 备份标注数据库。标注数据丢失等于人工工时作废，这个不能省。
# 部署在 ECS 上，由 cron 每日调用；保留最近 14 天。
set -eu

STACK=/opt/xmer-label
OUT="$STACK/backups"
KEEP_DAYS=14
STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$OUT"

docker exec "$(docker compose -f "$STACK/docker-compose.yml" ps -q db)" \
    pg_dump -U xmer -d xmer_annotation --no-owner \
    | gzip > "$OUT/xmer_annotation-$STAMP.sql.gz"

# 空转储说明备份失败，别把好备份轮换掉
if [ ! -s "$OUT/xmer_annotation-$STAMP.sql.gz" ]; then
    echo "备份为空，已中止轮换：$OUT/xmer_annotation-$STAMP.sql.gz" >&2
    exit 1
fi

find "$OUT" -name 'xmer_annotation-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "已备份 $OUT/xmer_annotation-$STAMP.sql.gz"
