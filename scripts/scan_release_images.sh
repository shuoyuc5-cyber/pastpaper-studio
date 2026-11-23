#!/usr/bin/env bash
set -Eeuo pipefail
release="${1:?Specify the image release tag}"
output="${2:?Specify a new absolute scanner output directory}"
[[ "$release" =~ ^[a-f0-9]{12,40}$ && "$output" = /* && ! -e "$output" ]] || exit 2
umask 077
mkdir -p "$output/cache"
scanner='ghcr.io/aquasecurity/trivy@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb'
docker run --rm -v "$output/cache:/cache" "$scanner" image --cache-dir /cache \
  --db-repository ghcr.io/aquasecurity/trivy-db:2 --download-db-only --no-progress --timeout 12m
status=0
for service in web backend; do
  docker image inspect "pastpaper-$service:$release" --format '{{.Id}}' > "$output/$service.image-id"
  docker image save "pastpaper-$service:$release" -o "$output/$service.tar"
  docker run --rm --network none -v "$output/cache:/cache" -v "$output/$service.tar:/image.tar:ro" "$scanner" \
    image --cache-dir /cache --skip-db-update --input /image.tar --scanners vuln,secret \
    --severity CRITICAL,HIGH --no-progress --format json --exit-code 1 > "$output/$service.json" || status=1
  rm -- "$output/$service.tar"
done
exit "$status"
