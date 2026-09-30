#!/bin/sh
# One-shot: create the platform buckets (spec §30) if they don't exist. Safe to run on every `compose up`.
set -eu

: "${S3_BUCKETS:?S3_BUCKETS is required}"
master="${SEAWEEDFS_MASTER:-seaweedfs:9333}"

existing=$(echo "s3.bucket.list" | weed shell -master="$master" 2>/dev/null || true)
for bucket in $(echo "$S3_BUCKETS" | tr ',' ' '); do
    if printf '%s\n' "$existing" | grep -Eq "^[[:space:]]*$bucket([[:space:]]|$)"; then
        echo "bucket exists: $bucket"
    else
        echo "s3.bucket.create -name $bucket" | weed shell -master="$master"
        echo "bucket created: $bucket"
    fi
done
