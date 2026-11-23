#!/usr/bin/env bash
# Build a candidate or source rollback in a fresh directory. Never changes the running release.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
if [[ $# != 3 ]]; then
  echo 'Usage: prepare_lan_release.sh SOURCE_REVISION LAUNCHER_REVISION NEW_RELEASE_DIRECTORY' >&2
  exit 2
fi
source_rev=$(git rev-parse --verify "$1^{commit}")
launcher_rev=$(git rev-parse --verify "$2^{commit}")
dest=$3
backend_port=${PASTPAPER_BACKEND_PORT:-8000}
mkdir "$dest"
dest=$(cd "$dest" && pwd)
git archive "$source_rev" | tar -x -C "$dest"
git show "$launcher_rev:outputs/start_studio.py" > "$dest/outputs/start_studio.py"
git show "$launcher_rev:backend/requirements-lock.txt" > "$dest/backend/requirements-lock.txt"
git show "$launcher_rev:backend/requirements.txt" > "$dest/backend/requirements.txt"
"${PASTPAPER_BUILD_PYTHON:-python3.14}" -m venv "$dest/backend/.venv"
runtime_python="$dest/backend/.venv/bin/python"
"$runtime_python" -m pip install -r "$dest/backend/requirements-lock.txt"
"$runtime_python" -m pip check
npm --prefix "$dest/frontend" ci --prefer-offline --no-fund
PASTPAPER_BACKEND_PORT="$backend_port" npm --prefix "$dest/frontend" run build
"$runtime_python" - "$dest" "$source_rev" "$launcher_rev" "$backend_port" <<'PY'
import certifi, json, ssl, sys
from pathlib import Path
dest, source, launcher, port = sys.argv[1:]
roots = ssl.create_default_context(cafile=certifi.where()).get_ca_certs()
if any(('commonName','emSign ECC Root CA - G3') in rdn for cert in roots for rdn in cert['subject']):
    raise SystemExit('Affected root is still trusted')
manifest = dict(source_commit=source,launcher_commit=launcher,backend_port=int(port),
                python=sys.version.split()[0],certifi=certifi.__version__,trusted_roots=len(roots))
(Path(dest)/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest))
PY
