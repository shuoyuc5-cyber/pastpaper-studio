"""Check an independent store without printing paths, document names or student data."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from contextlib import closing


def check(root):
    database = root/'pastpaper_studio.sqlite3'
    marker = (root/'.pastpaper-public').read_text().strip()
    stats = dict(verified=0,missing=0,digest_mismatch=0,invalid_path=0)
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('BEGIN')
        profile = conn.execute("SELECT value FROM settings WHERE key='independent_public_origin'").fetchone()
        if not profile or profile[0]!=marker:
            raise RuntimeError('Independent profile mismatch')
        if conn.execute('PRAGMA integrity_check').fetchone()!=('ok',):
            raise RuntimeError('SQLite integrity check failed')
        foreign_keys = sum(1 for _ in conn.execute('PRAGMA foreign_key_check'))
        wal = conn.execute('PRAGMA journal_mode').fetchone()[0]
        for pathname, owner, expected in conn.execute("""SELECT path,owner_id,file_hash FROM source_files
                WHERE status IN ('completed','duplicate','needs_review')"""):
            path = Path(pathname)
            expected_root = root/'uploads'/owner
            if not expected_root.is_relative_to(root/'uploads') or not path.is_relative_to(expected_root) or path.resolve()!=path:
                stats['invalid_path'] += 1
                continue
            try:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream,'sha256').hexdigest()
            except OSError:
                stats['missing'] += 1
                continue
            stats['verified' if expected and digest==expected else 'digest_mismatch'] += 1
    print(json.dumps(dict(stats,wal=wal,foreign_key_errors=foreign_keys),sort_keys=True))
    return wal=='wal' and not foreign_keys and not any(stats[k] for k in ('missing','digest_mismatch','invalid_path'))


if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('Specify the independent data directory')
    raise SystemExit(0 if check(Path(sys.argv[1]).resolve()) else 1)
