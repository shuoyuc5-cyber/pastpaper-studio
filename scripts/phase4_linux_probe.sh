#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
image="${1:?Select a locally built PastPaper Linux validation image}"
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges=true \
  --memory 3g --cpus 2 --pids-limit 256 "$image" bash -euc '
  cd /studio
  PYTHONPATH=backend python -c "from app.pdf_sandbox import run; out=run(\"probe\",\"/etc/passwd\"); assert all(out.values()),out; print(\"PASS Linux Landlock filesystem and seccomp socket denial\")"
  python -c "import certifi,ssl; c=ssl.create_default_context(cafile=certifi.where()); assert not any(\"emSign ECC Root CA - G3\" in str(a[\"subject\"]) for a in c.get_ca_certs()); print(\"PASS certifi trust anchor check\",certifi.__version__)"
  for check in verify_security verify_v3_security verify_classroom verify_classwork verify_duplicates verify_builder_drafts verify_host_update verify_ai_permissions verify_ocr_layout_cloud verify_audit_boundaries; do
    python "backend/scripts/$check.py"
  done
  node --test tests/*.test.mjs
  PASTPAPER_TEST_EXTENDED_LOAD=1 python scripts/local_fullstack.py verify
'
