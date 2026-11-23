#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
release="${1:?Use a locally built 12-character release}"
project=pastpaper-qa-phase4-$$
fixture="$(mktemp -d)"
umask 077
settings="$fixture/settings.env"
cat > "$settings" <<EOF
STUDIO_ORIGIN=https://phase4.example.org
STUDIO_ENV_FILE=$fixture/container.env
STUDIO_STATE=$fixture/state
STUDIO_SECRETS=$fixture/secrets
STUDIO_MAIL_SECRETS=$fixture/mail
STUDIO_CAPTURE=$fixture/capture
EOF
sed 's@https://staging.example.org@https://phase4.example.org@' deploy/fullstack/container.env.example > "$fixture/container.env"
export STUDIO_RELEASE="$release"
ops=(scripts/controlled_release.sh "$project" "$settings")
compose=(docker compose -p "$project" --env-file "$settings" -f deploy/fullstack/compose.release.yml)
trap '"${compose[@]}" down >/dev/null 2>&1 || true; printf "Synthetic fixture: %s\n" "$fixture"' EXIT
mkdir "$fixture"/{state,secrets,mail,capture,backup,restore}
# The local test directory is synthetic. Use a temporary root helper only to match Linux service ownership.
docker run --rm --network none --user 0 -v "$fixture:/fixture" "pastpaper-backend:$release" python -c '
import base64, os, secrets
from pathlib import Path
from cryptography.fernet import Fernet
root=Path("/fixture")
def save(path,data):
    path.write_bytes(data)
    path.chmod(0o600)
    os.chown(path,10001,10001)
save(root/"state"/".pastpaper-public",b"https://phase4.example.org")
save(root/"secrets"/"admin-totp",base64.b32encode(secrets.token_bytes(20)))
key=Fernet.generate_key()
save(root/"secrets"/"mail-fernet",key)
save(root/"mail"/"mail-fernet",key)
for key in ("state","secrets","mail","capture","backup","restore"):
    os.chown(root/key,10001,10001)
'
"${ops[@]}" config "$release"
"${compose[@]}" up -d --pull never web
"${compose[@]}" run -T --rm --no-deps api python scripts/public_service.py bootstrap QA operator@example.test <<<"Synthetic phase4 test credentials only"
"${ops[@]}" up "$release"
"${compose[@]}" exec -T web node <<'JS'
const http = require('node:http');
const assert = require('node:assert/strict');
function request(path,headers={}) {
  return new Promise((resolve,reject) => {
    http.get({host:'127.0.0.1',port:3000,path,headers:{host:'phase4.example.org',...headers}}, response=>{
      response.resume();
      response.on('end',()=>resolve(response.statusCode));
    }).on('error',reject);
  });
}
(async()=>{
  assert.equal(await request('/api/health'),403);
  assert.equal(await request('/api/health',{'cf-connecting-ip':'192.0.2.9'}),200);
  assert.equal(await request('/api/papers',{'cf-connecting-ip':'192.0.2.9'}),401);
  assert.equal(await request('/',{'cf-connecting-ip':'192.0.2.9'}),200);
  console.log('PASS release gateway and authentication smoke');
})().catch(error=>{console.error(error);process.exitCode=1;});
JS
for service in web api pdf-worker mail-worker; do
  case "$service" in
    web) expected='536870912 1000000000 128' ;;
    api) expected='1258291200 1500000000 128' ;;
    pdf-worker) expected='943718400 1000000000 64' ;;
    mail-worker) expected='268435456 500000000 48' ;;
  esac
  container="$("${compose[@]}" ps -q "$service")"
  [[ "$(docker inspect --format '{{len .HostConfig.PortBindings}} {{.HostConfig.ReadonlyRootfs}} {{.Config.User}} {{.HostConfig.Privileged}} {{json .HostConfig.CapDrop}} {{len .HostConfig.CapAdd}} {{json .HostConfig.SecurityOpt}}' "$container")" = '0 true 10001:10001 false ["ALL"] 0 ["no-new-privileges:true"]' ]]
  [[ "$(docker inspect --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}' "$container")" = "$expected" ]]
  if [[ "$service" == pdf-worker ]]; then
    [[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$container")" = none ]]
  fi
  printf 'PASS %s container restrictions and memory/CPU/PID limits %s\n' "$service" "$expected"
done
"${ops[@]}" verify "$release"
"${ops[@]}" monitor "$release"
"${ops[@]}" snapshot "$release" "$fixture/backup" smoke
"${ops[@]}" restore "$release" "$fixture/backup/smoke" "$fixture/restore" fresh
"${compose[@]}" stop pdf-worker mail-worker
"${compose[@]}" up -d --wait --wait-timeout 60 pdf-worker mail-worker
"${ops[@]}" health "$release"
printf '%s\n' 'PASS split Compose deployment, no host ports, consistent snapshot and isolated restore, worker restart'
if [[ "${PASTPAPER_QA_TEST_ROLLBACK:-0}" = 1 ]]; then
  broken="$(printf '%s' "$project" | shasum -a 256 | cut -c1-12)"
  printf 'FROM pastpaper-backend:%s\nCMD ["sleep","infinity"]\n' "$release" |
    docker build -t "pastpaper-backend:$broken" -
  docker tag "pastpaper-web:$release" "pastpaper-web:$broken"
  STUDIO_RELEASE="$broken" "${compose[@]}" up -d --no-deps --pull never api
  if "${ops[@]}" health "$broken"; then
    echo 'Invalid runtime passed readiness check' >&2
    exit 1
  fi
  "${ops[@]}" rollback "$broken" "$release"
  "${ops[@]}" verify "$release"
  docker image rm "pastpaper-web:$broken" "pastpaper-backend:$broken" >/dev/null
  printf '%s\n' 'PASS deliberately unhealthy image rejected and known-good image restored'
fi
