#!/bin/sh
# SeaweedFS (ADR-015): master + volume + filer + S3 gateway in one container.
# The S3 identity file is generated at start from S3_ACCESS_KEY / S3_SECRET_KEY, so no secret lives in the repo.
# The application key may only read/write/list the platform buckets (spec §30), nothing else.
set -eu

: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
: "${S3_BUCKETS:?S3_BUCKETS is required}"

# Keys are written into JSON below; allow only characters that need no escaping.
for value in "$S3_ACCESS_KEY" "$S3_SECRET_KEY"; do
    case "$value" in
        *[!A-Za-z0-9._~+/=-]*) echo "S3_ACCESS_KEY/S3_SECRET_KEY may contain only A-Z a-z 0-9 . _ ~ + / = -" >&2; exit 1 ;;
    esac
done

actions=""
for bucket in $(echo "$S3_BUCKETS" | tr ',' ' '); do
    for action in Read Write List Tagging; do
        actions="${actions:+$actions,}\"$action:$bucket\""
    done
done

umask 077
cat > /tmp/s3.json <<EOF
{
  "identities": [
    {
      "name": "app",
      "credentials": [{"accessKey": "$S3_ACCESS_KEY", "secretKey": "$S3_SECRET_KEY"}],
      "actions": [$actions]
    }
  ]
}
EOF

exec weed server \
    -dir=/data \
    -ip=seaweedfs -ip.bind=0.0.0.0 \
    -master.volumeSizeLimitMB=1024 -volume.max=0 \
    -s3 -s3.port=8333 -s3.config=/tmp/s3.json
