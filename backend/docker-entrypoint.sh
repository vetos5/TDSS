#!/bin/sh
# Container start-up: seed an empty corpus volume once, make the data volumes writable, then run
# the server as an unprivileged user (PUID / PGID, default 1000, as on most NAS systems).
set -eu

DOCS=/opt/tdss/corpus/documents
SEED=/opt/tdss/corpus/seed
CACHE=/opt/tdss/.cache
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

mkdir -p "$DOCS" "$CACHE/gis"

# The marker keeps deleted demo documents deleted across restarts and image updates.
if [ "${TDSS_SEED_DEMO:-1}" = "1" ] && [ ! -e "$DOCS/.seeded" ] && [ -z "$(ls -A "$DOCS")" ]; then
    cp -r "$SEED"/. "$DOCS"/
    echo "tdss: seeded $DOCS with the demo corpus (set TDSS_SEED_DEMO=0 to start empty)"
fi
touch "$DOCS/.seeded"

if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then
    chown -R "$PUID:$PGID" "$DOCS" "$CACHE"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi
exec "$@"
