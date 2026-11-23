#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
audit_python="${PASTPAPER_AUDIT_PYTHON:-$PWD/backend/.venv/bin/python}"
"$audit_python" -m pip check
"$audit_python" -m compileall -q backend/app backend/scripts scripts
for check in verify_security verify_v3_security verify_classroom verify_classwork verify_duplicates \
  verify_builder_drafts verify_host_update verify_ai_permissions verify_ocr_layout_cloud verify_audit_boundaries; do
  "$audit_python" "backend/scripts/$check.py"
done
node --test tests/*.test.mjs
for module in frontend/server-*.cjs frontend/public/device/*.mjs deploy/cloudflare/*.mjs; do
  node --check "$module"
done
npm --prefix frontend run build
