#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
die() { printf '%s\n' "$*" >&2; exit 1; }
project="${1:?Supply a separate Compose project name}"
settings="${2:?Supply an absolute settings env path}"
action="${3:?Use config, build, up, health, logs, snapshot, restore, rollback or stop}"
release="${4:?Supply a commit-derived image tag}"
[[ "$project" =~ ^pastpaper-(qa|staging|prod)-[a-z0-9][a-z0-9-]*$ ]] || die "Use a dedicated PastPaper project."
[[ "$settings" = /* && -f "$settings" && "$release" =~ ^[a-f0-9]{12,40}$ ]] || die "Invalid settings path or image tag."
unset STUDIO_ORIGIN STUDIO_ENV_FILE STUDIO_STATE STUDIO_SECRETS STUDIO_MAIL_SECRETS STUDIO_CAPTURE
export STUDIO_RELEASE="$release"
compose=(docker compose -p "$project" --env-file "$settings" -f deploy/fullstack/compose.release.yml)
if [[ "$project" = pastpaper-prod-* ]]; then compose+=(-f deploy/fullstack/compose.production.yml); fi
health() {
  "${compose[@]}" exec -T api python -c 'import json,urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8000/api/health",timeout=4); assert json.load(r)["status"]=="ok"'
  "${compose[@]}" exec -T web node -e 'const http=require("node:http"); const u=new URL(process.env.PASTPAPER_PUBLIC_ORIGIN); const q=http.get({host:"127.0.0.1",port:3000,path:"/api/health",headers:{host:u.host,"cf-connecting-ip":"127.0.0.1"}},r=>{r.resume(); if(r.statusCode!==200){console.error("Gateway status",r.statusCode);process.exitCode=1}else console.log("Frontend gateway and SQLite health OK")});q.on("error",()=>process.exitCode=1);q.setTimeout(4000,()=>q.destroy())'
}
verify_images() {
  for service in web backend; do
    docker image inspect "pastpaper-${service}:${STUDIO_RELEASE}" --format '{{.Id}}'
  done
}
case "$action" in
  bootstrap)
    username="${5:?Supply an independent administrator name}"
    email="${6:?Supply an independent administrator email}"
    "${compose[@]}" up -d --pull never web
    "${compose[@]}" run --rm --no-deps api python scripts/public_service.py bootstrap "$username" "$email"
    ;;
  config) "${compose[@]}" config -q ;;
  build)
    [[ "$(git rev-parse HEAD)" = "$release"* && -z "$(git status --porcelain)" ]] || die "Build a clean checkout at the requested commit."
    for service in backend web; do
      docker build -f deploy/fullstack/Dockerfile.release --target "$service" --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" -t "pastpaper-${service}:$release" .
    done ;;
  up)
    verify_images
    "${compose[@]}" up -d --wait --wait-timeout 90 --pull never
    health ;;
  health) health ;;
  verify) "${compose[@]}" exec -T api python scripts/verify_public_storage.py /state ;;
  monitor) "${compose[@]}" exec -T api python scripts/monitor_public.py ;;
  logs) "${compose[@]}" logs --tail 100 ;;
  snapshot)
    base="${5:?Supply an absolute private backup directory}"
    name="${6:?Supply a new backup name}"
    [[ "$base" = /* && -d "$base" && "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ && ! -e "$base/$name" ]] || die "Choose a fresh backup destination."
    "${compose[@]}" run -T --rm --no-deps -v "$base:/backup" api python scripts/audit_backup.py snapshot /state "/backup/$name"
    ;;
  restore)
    source="${5:?Supply the absolute snapshot path}"
    parent="${6:?Supply a separate absolute restore directory}"
    name="${7:?Supply a fresh restore name}"
    [[ "$source" = /* && -f "$source/manifest.json" && "$parent" = /* && -d "$parent" && "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ && ! -e "$parent/$name" ]] || die "Choose a verified snapshot and a fresh destination."
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges=true \
      -v "$source:/snapshot:ro" -v "$parent:/restore" "pastpaper-backend:$release" \
      python scripts/audit_backup.py restore /snapshot "/restore/$name" --runtime-dir /state
    ;;
  rollback)
    previous="${5:?Supply a known-good compatible tag}"
    [[ "$previous" =~ ^[a-f0-9]{12,40}$ && "$previous" != "$release" ]] || die "Invalid rollback tag."
    export STUDIO_RELEASE="$previous"
    verify_images
    "${compose[@]}" up -d --wait --wait-timeout 90 --pull never
    health ;;
  stop) "${compose[@]}" stop ;;
  *) die "Unknown action: $action" ;;
esac
