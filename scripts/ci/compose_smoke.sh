#!/usr/bin/env bash
# End-to-end smoke test of the compose stack (M01). Used by CI; also runnable locally:
#   scripts/ci/compose_smoke.sh            # creates a throwaway .env if none exists, tears everything down after
# Checks: every service healthy, nginx -> API routing + request-id propagation, object-store permissions
# (app key limited to platform buckets, anonymous and wrong-key access denied), and no internet from the data network.
set -euo pipefail

cd "$(dirname "$0")/../.."
created_env=0
if [[ ! -f .env ]]; then
    rand() { python3 -c "import secrets; print(secrets.token_hex(16))"; }
    sed -e "s/^POSTGRES_PASSWORD=CHANGE_ME/POSTGRES_PASSWORD=$(rand)/" \
        -e "s/^REDIS_PASSWORD=CHANGE_ME/REDIS_PASSWORD=$(rand)/" \
        -e "s/^S3_ACCESS_KEY=CHANGE_ME/S3_ACCESS_KEY=$(rand)/" \
        -e "s/^S3_SECRET_KEY=CHANGE_ME/S3_SECRET_KEY=$(rand)/" \
        -e "s/^HTTP_PORT=.*/HTTP_PORT=${SMOKE_HTTP_PORT:-28481}/" \
        .env.example > .env
    created_env=1
fi

cleanup() {
    status=$?
    if [[ $status -ne 0 ]]; then docker compose ps -a; docker compose logs --tail 50; fi
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
    [[ $created_env -eq 1 ]] && rm -f .env
    exit $status
}
trap cleanup EXIT

set -a; source .env; set +a
base="http://${HTTP_BIND}:${HTTP_PORT}"
fail() { echo "FAIL: $*" >&2; exit 1; }
expect() {  # expect <name> <wanted> <got>
    if [[ "$3" == "$2" ]]; then echo "ok   $1 ($3)"; else fail "$1: wanted $2, got $3"; fi
}

docker compose up -d --build --wait --wait-timeout 300

expect "health via nginx" 200 "$(curl -s -o /dev/null -w '%{http_code}' "$base/health")"
expect "request id round trip" smoke-1 \
    "$(curl -s -D - -o /dev/null -H 'X-Request-ID: smoke-1' "$base/health" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-request-id"{print $2}')"
expect "unknown API route uses error envelope" not_found \
    "$(curl -s "$base/api/v1/does-not-exist" | python3 -c 'import json,sys; print(json.load(sys.stdin)["error"]["code"])')"

s3() {  # s3 <user:secret or ""> <curl args...>  -> HTTP status, from inside the data network
    local auth=()
    [[ -n "$1" ]] && auth=(--aws-sigv4 "aws:amz:us-east-1:s3" --user "$1")
    shift
    docker run --rm --network yas_data curlimages/curl:8.16.0 -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$@"
}
key="$S3_ACCESS_KEY:$S3_SECRET_KEY"
obj="http://seaweedfs:8333/ai-video-assets/smoke-$$.txt"
expect "app key writes platform bucket" 200 "$(s3 "$key" -X PUT --data-binary hello "$obj")"
expect "app key reads platform bucket" 200 "$(s3 "$key" "$obj")"
expect "app key cannot create other buckets" 403 "$(s3 "$key" -X PUT http://seaweedfs:8333/not-a-platform-bucket)"
expect "wrong secret denied" 403 "$(s3 "$S3_ACCESS_KEY:wrong" "$obj")"
expect "anonymous read denied" 403 "$(s3 "" "$obj")"
expect "app key deletes its object" 204 "$(s3 "$key" -X DELETE "$obj")"

internet=$(docker run --rm --network yas_data curlimages/curl:8.16.0 -s -m 5 -o /dev/null -w '%{http_code}' https://example.com || true)
expect "data network has no internet" 000 "$internet"

published=$(docker compose ps --format json | python3 -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin if line.strip()]
rows = rows[0] if len(rows) == 1 and isinstance(rows[0], list) else rows
print(",".join(sorted({r["Service"] for r in rows for p in r.get("Publishers") or [] if p.get("PublishedPort")})))')
expect "only nginx publishes a port" nginx "$published"

echo "compose smoke test passed"
