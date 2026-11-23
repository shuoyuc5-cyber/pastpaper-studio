"""On-host readiness and queue monitor. Prints aggregate JSON for a private alert collector."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from urllib.request import build_opener, ProxyHandler

root = Path(os.environ['PASTPAPER_DATA_DIR']).resolve()
problems = []
try:
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:8000/api/health',timeout=4) as reply:
        if json.load(reply).get('status')!='ok':
            problems.append('api_unhealthy')
except (OSError, ValueError):
    problems.append('api_unreachable')
with closing(sqlite3.connect((root/'pastpaper_studio.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
    queued, oldest = db.execute("SELECT COUNT(*),MIN(updated_at) FROM source_files WHERE status IN('waiting','processing')").fetchone()
    mail = dict(db.execute("SELECT state,COUNT(*) FROM public_outbox GROUP BY state"))
age = (datetime.now(timezone.utc)-datetime.fromisoformat(oldest)).total_seconds() if oldest else 0
free = shutil.disk_usage(root).free
if age>300:
    problems.append('pdf_queue_lag')
if mail.get('uncertain') or mail.get('failed'):
    problems.append('mail_delivery')
if free<2*1024**3:
    problems.append('disk_low')
print(json.dumps({'alerts':problems,'pending_pdf':queued,'oldest_pdf_seconds':round(age),
                  'mail_counts':mail,'available_bytes':free},sort_keys=True))
sys.exit(1 if problems else 0)
