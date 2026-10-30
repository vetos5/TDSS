#!/bin/sh
# TDSS continuous deployment for ZimaOS: a pull-based watcher, started by
# deploy/zima/docker-compose.yml.
#
# Every TDSS_POLL_SECONDS it asks GitHub for the head of TDSS_BRANCH. A new commit is deployed
# once its GitHub Actions checks have passed:
#   1. download the commit's tarball into $SRC.new;
#   2. build the images (the running site is untouched if this fails);
#   3. recreate the containers and wait until the backend is healthy and nginx serves the API;
#   4. on success keep the source in $SRC; otherwise put the previous images back and recreate.
# A commit that builds but does not start is not retried (it would fail the same way); a failed
# download or build is retried, since the running site is untouched by those.
# Nothing listens for connections. The box only makes outbound requests to GitHub, so pull
# requests from forks cannot run anything here: only commits on the branch are deployed.
set -u

REPO="${TDSS_REPO:-vetos5/TDSS}"
BRANCH="${TDSS_BRANCH:-main}"
INTERVAL="${TDSS_POLL_SECONDS:-60}"
REQUIRE_CI="${TDSS_REQUIRE_CI:-1}"
API="${TDSS_GITHUB_API:-https://api.github.com}"
HOME_DIR="${TDSS_HOME:-/DATA/AppData/tdss}"
STATE="$HOME_DIR/deployer"
SRC="$HOME_DIR/src"
COMPOSE_FILE=docker-compose.zima.yml
MAX_ATTEMPTS=3          # failed deploys of one commit before waiting for the next commit
HEALTH_TIMEOUT="${TDSS_HEALTH_TIMEOUT:-180}"   # seconds for a new version to become healthy

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >&2; }

# curl with the optional token (needed only for a private repository or a higher rate limit).
gh_curl() {
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" "$@"
    else
        curl -sS "$@"
    fi
}

header() { grep -i "^$1:" "$STATE/headers" | tail -n 1 | cut -d' ' -f2- | tr -d '\r'; }

# GET an API path into a file; prints the HTTP status. A 304 for an unchanged ETag does not
# count against GitHub's rate limit, which is what makes polling every minute affordable.
api_get() {
    local path="$1" out="$2" if_none_match="${3:-}"
    if [ -n "$if_none_match" ]; then
        gh_curl -o "$out" -D "$STATE/headers" -w '%{http_code}' -H "Accept: application/vnd.github+json" \
            -H "If-None-Match: $if_none_match" "$API$path"
    else
        gh_curl -o "$out" -D "$STATE/headers" -w '%{http_code}' -H "Accept: application/vnd.github+json" "$API$path"
    fi
}

rate_limited() {
    local reset wait
    reset=$(header x-ratelimit-reset)
    wait=$(( ${reset:-0} - $(date +%s) ))
    [ "$wait" -gt 3600 ] && wait=3600
    [ "$wait" -lt "$INTERVAL" ] && wait=$INTERVAL
    log "GitHub rate limit reached; next check in ${wait}s (set GITHUB_TOKEN for a higher limit)"
    sleep "$wait"
}

# success | pending | failure for the GitHub Actions checks of a commit. A re-run job counts by
# its latest attempt; a commit without any checks yet is pending.
ci_state() {
    local code
    code=$(api_get "/repos/$REPO/commits/$1/check-runs?per_page=100" "$STATE/checks.json")
    case $code in
        200) ;;
        403|429) rate_limited; echo pending; return ;;
        *) echo pending; return ;;
    esac
    jq -r '[.check_runs[] | select(.app.slug == "github-actions")]
        | group_by(.name) | map(max_by(.started_at // ""))
        | if length == 0 then "pending"
          elif any(.[]; .status != "completed") then "pending"
          elif any(.[]; (.conclusion | IN("success", "skipped", "neutral")) | not) then "failure"
          else "success" end' "$STATE/checks.json" 2>/dev/null || echo pending
}

compose() { (cd "$1" && shift && docker compose -f "$COMPOSE_FILE" "$@"); }

healthy() {
    local dir="$1" waited=0 backend status
    while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
        backend=$(compose "$dir" ps -q backend)
        status=$(docker inspect -f '{{.State.Health.Status}}' "$backend" 2>/dev/null)
        [ "$status" = unhealthy ] && return 1
        # A backend that crashes on start is restarted by Docker: no need to wait it out.
        [ "$(docker inspect -f '{{.RestartCount}}' "$backend" 2>/dev/null || echo 0)" -gt 0 ] && return 1
        # Through nginx to the backend: proves both containers and the proxy work.
        if [ "$status" = healthy ] && compose "$dir" exec -T frontend wget -qO /dev/null http://127.0.0.1/api/contexts; then
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    return 1
}

# 0 deployed, 1 failed (retried), 2 this commit cannot be deployed (not retried).
deploy() {
    local sha="$1" short code image
    short=$(echo "$sha" | cut -c1-7)
    log "deploying $short"
    rm -rf "$SRC.new" && mkdir -p "$SRC.new"
    code=$(gh_curl -L -o "$STATE/source.tar.gz" -w '%{http_code}' "$API/repos/$REPO/tarball/$sha")
    # -m: extraction time as mtime. BuildKit resends context files by size and mtime, and archive
    # mtimes can repeat between commits, so an old file could otherwise be built.
    if [ "$code" != 200 ] || ! tar -xzmf "$STATE/source.tar.gz" -C "$SRC.new" --strip-components=1; then
        log "could not download $short (HTTP $code)"
        return 1
    fi
    rm -f "$STATE/source.tar.gz"
    if [ ! -f "$SRC.new/$COMPOSE_FILE" ]; then
        log "$short has no $COMPOSE_FILE; nothing to deploy"
        return 2
    fi
    # Settings for the app (TDSS_PORT, TZ, ANTHROPIC_API_KEY, ...) live outside the source tree.
    [ -f "$HOME_DIR/app.env" ] && cp "$HOME_DIR/app.env" "$SRC.new/.env"

    # Keep the current images under a :rollback tag. A tag rather than an image id: with the
    # containerd image store, an image whose tag moves to a new build is deleted at once.
    compose "$SRC.new" config --images > "$STATE/images" || return 1
    : > "$STATE/rollback-images"
    while read -r image; do
        if docker image inspect "$image" > /dev/null 2>&1; then
            docker tag "$image" "${image%:*}:rollback" && echo "$image" >> "$STATE/rollback-images"
        fi
    done < "$STATE/images"

    if ! compose "$SRC.new" build; then
        log "build of $short failed; the running version is unchanged"
        return 1
    fi
    compose "$SRC.new" up -d --force-recreate --remove-orphans || true
    if healthy "$SRC.new"; then
        rm -rf "$SRC.previous"
        [ -d "$SRC" ] && mv "$SRC" "$SRC.previous"
        mv "$SRC.new" "$SRC"
        docker image prune -f > /dev/null
        log "deployed $short"
        return 0
    fi

    log "$short did not become healthy; rolling back"
    compose "$SRC.new" logs --tail 30 backend frontend 2>&1 | sed 's/^/    /'
    while read -r image; do docker tag "${image%:*}:rollback" "$image"; done < "$STATE/rollback-images"
    if [ -d "$SRC" ] && [ -s "$STATE/rollback-images" ]; then
        compose "$SRC" up -d --force-recreate --remove-orphans && log "previous version restored"
    else
        log "no previous version to restore"
    fi
    return 2
}

# After a deploy, run the deployer that came with it if it changed (it updates itself).
self_update() {
    local new="$SRC/deploy/zima/deployer.sh"
    if [ -f "$new" ] && ! cmp -s "$new" "$0"; then
        cp "$new" "$STATE/deployer.sh.new" && mv "$STATE/deployer.sh.new" "$STATE/deployer.sh"
        log "deployer updated; restarting it"
        exec sh "$STATE/deployer.sh"
    fi
}

mkdir -p "$STATE"
# TDSS_DATA (the app's data folder) follows TDSS_HOME unless app.env sets it.
if ! grep -qs '^TDSS_DATA=' "$HOME_DIR/app.env"; then export TDSS_DATA="$HOME_DIR"; fi

deployed=$(cat "$STATE/deployed" 2>/dev/null || true)
log "watching $REPO@$BRANCH every ${INTERVAL}s (deployed: $(echo "${deployed:-none}" | cut -c1-7), CI required: $REQUIRE_CI)"

etag="" sha="" given_up="" waiting="" attempts=0
while :; do
    code=$(api_get "/repos/$REPO/commits/$BRANCH" "$STATE/commit.json" "$etag")
    case $code in
        200) etag=$(header etag); sha=$(jq -r '.sha // empty' "$STATE/commit.json") ;;
        304) ;;
        403|429) rate_limited; continue ;;
        *) log "GitHub answered HTTP $code for $REPO@$BRANCH" ;;
    esac

    if [ -n "$sha" ] && [ "$sha" != "$deployed" ] && [ "$sha" != "$given_up" ]; then
        short=$(echo "$sha" | cut -c1-7)
        ci=success
        [ "$REQUIRE_CI" = 1 ] && ci=$(ci_state "$sha")
        case $ci in
            pending)
                [ "$waiting" != "$sha" ] && log "new commit $short; waiting for CI" && waiting=$sha ;;
            failure)
                log "CI failed for $short; not deploying it"
                given_up=$sha ;;
            success)
                deploy "$sha"
                result=$?
                if [ "$result" = 0 ]; then
                    deployed=$sha attempts=0
                    echo "$sha" > "$STATE/deployed"
                    echo "$(date '+%Y-%m-%d %H:%M:%S') $sha" >> "$STATE/history.log"
                    self_update
                elif [ "$result" = 2 ]; then
                    given_up=$sha
                else
                    attempts=$((attempts + 1))
                    if [ "$attempts" -ge "$MAX_ATTEMPTS" ]; then
                        log "giving up on $short after $attempts attempts; waiting for a new commit"
                        given_up=$sha attempts=0
                    fi
                fi ;;
        esac
    fi
    sleep "$INTERVAL"
done
