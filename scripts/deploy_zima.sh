#!/bin/sh
# Deploy TDSS to a ZimaOS (or any Docker) machine over SSH: copy the source, build the images on
# the machine and (re)start the stack. Uploaded corpus documents and the GIS cache live in
# /DATA/AppData/tdss and survive redeploys.
#
#   scripts/deploy_zima.sh root@192.168.31.10            # host as an argument
#   ZIMA_HOST=root@zimaos.local scripts/deploy_zima.sh   # or in the environment
#
# Optional: ZIMA_DIR (default /DATA/AppData/tdss/src). A .env file in the repository root is
# copied along and read by docker compose (TDSS_PORT, TZ, TDSS_SEED_DEMO, ...).
set -eu

HOST="${1:-${ZIMA_HOST:-}}"
DIR="${ZIMA_DIR:-/DATA/AppData/tdss/src}"
if [ -z "$HOST" ]; then
    echo "usage: $0 user@zima-host   (or set ZIMA_HOST)" >&2
    exit 2
fi

cd "$(dirname "$0")/.."

echo "==> Copying the source to $HOST:$DIR"
# tar rather than rsync: ZimaOS does not ship rsync. The remote copy is replaced, not merged,
# so files deleted locally disappear there too. Data volumes are outside $DIR.
COPYFILE_DISABLE=1 tar -czf - \
    --exclude=.git --exclude=.venv --exclude=venv --exclude=node_modules --exclude=dist \
    --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache --exclude=.cache \
    --exclude=.sf --exclude=legacy --exclude=.DS_Store \
    . | ssh "$HOST" "rm -rf '$DIR.new' && mkdir -p '$DIR.new' && tar -xzf - -C '$DIR.new' \
        && rm -rf '$DIR' && mv '$DIR.new' '$DIR'"

echo "==> Building and starting on $HOST (the first build takes a few minutes)"
# Build first, then recreate: `up --build` alone can keep the old containers running on the
# previous images when the tag moves, so a redeploy would silently serve the old version.
ssh "$HOST" "cd '$DIR' && docker compose -f docker-compose.zima.yml build \
    && docker compose -f docker-compose.zima.yml up -d --force-recreate --remove-orphans \
    && docker image prune -f >/dev/null && docker compose -f docker-compose.zima.yml ps"

PORT="$(sed -n 's/^TDSS_PORT=//p' .env 2>/dev/null | tail -n 1)"
echo "==> Done: http://${HOST#*@}:${PORT:-8580}"
