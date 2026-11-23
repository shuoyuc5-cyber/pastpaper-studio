"""Make and verify a private, local-only snapshot; restore only to a fresh directory."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from stat import S_ISREG
import tempfile

DB = 'pastpaper_studio.sqlite3'
SUBDIRS = ('uploads', 'answers', 'duplicate_trash', 'ocr')


def ro(path):
    return sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=10)


def stamp(path):
    s = path.lstat()
    if not S_ISREG(s.st_mode):
        raise ValueError('Snapshot source is not a regular file')
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def digest(path, destination=None):
    h = hashlib.sha256()
    with path.open('rb') as stream, (
        destination.open('xb') if destination else open(os.devnull, 'wb')
    ) as output:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
            if destination:
                output.write(block)
    return h.hexdigest()


def contents(data, conn):
    result = {}
    for prefix in SUBDIRS:
        tree = data / prefix
        for path in tree.rglob('*'):
            if path.is_file() and not path.is_symlink() and not path.name.startswith('.upload-'):
                result[str(path.relative_to(data))] = path
    row = conn.execute("SELECT value FROM settings WHERE key='source_folder'").fetchone()
    folder = Path(row[0]).expanduser().resolve() if row and row[0] else None
    if folder and not folder.is_dir():
        raise ValueError('Configured source directory is unavailable; cannot verify a complete PDF backup')
    external = {p.resolve() for p in folder.rglob('*') if p.suffix.lower()=='.pdf'
                and p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(folder)} if folder else set()
    recorded = {Path(row[0]) for row in conn.execute("SELECT path FROM source_files WHERE status<>'deleted'")}
    unavailable = sum(not path.is_file() for path in recorded)
    external |= {p for p in recorded if p.suffix.lower()=='.pdf' and p.is_file()
                 and not p.is_symlink() and p.resolve()==p and not p.is_relative_to(data)}
    for idx, path in enumerate(sorted(external)):
        if not path.is_relative_to(data):
            result[f'external/{idx:06d}.pdf'] = path
    return result, unavailable


def verify(root, manifest):
    for relative, entry in manifest['files'].items():
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink() or digest(path) != entry['sha256']:
            raise ValueError('Snapshot checksum mismatch')
    with closing(ro(root / DB)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')

def file_state(conn):
    return (
        conn.execute('SELECT id,path,file_hash,size_bytes,mtime_ns FROM source_files ORDER BY id').fetchall(),
        conn.execute('SELECT id,path FROM attachments ORDER BY id').fetchall(),
        conn.execute("SELECT key,value FROM settings WHERE key='source_folder' OR key LIKE 'duplicate_trash:%' ORDER BY key").fetchall(),
    )


def snapshot(data, destination):
    if destination.exists() or destination.is_relative_to(data):
        raise ValueError('Choose a new snapshot directory outside of the data folder')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=destination.parent) as stage:
        root = Path(stage) / 'snapshot'
        root.mkdir(mode=0o700)
        owned = {}
        with closing(ro(data / DB)) as source:
            with closing(sqlite3.connect(root / DB)) as copied:
                source.backup(copied)
            with closing(ro(root / DB)) as copied:
                paths, unavailable = contents(data, copied)
                state = file_state(copied)
            stamps = {key: stamp(path) for key, path in paths.items()}
            for key, path in paths.items():
                target = root / key
                target.parent.mkdir(parents=True, exist_ok=True)
                owned[key] = {'sha256': digest(path, target), 'source': str(path)}
            with closing(ro(root / DB)) as copied:
                after, _ = contents(data, copied)
            source.execute('BEGIN')
            if paths != after or state != file_state(source) or any(stamps[key] != stamp(path) for key, path in paths.items()):
                raise ValueError('Source files changed during snapshot. Retry during an idle window.')
        owned[DB] = {'sha256': digest(root / DB)}
        manifest = {'files': owned, 'unavailable_records_at_source': unavailable}
        (root / 'manifest.json').write_text(json.dumps(manifest))
        verify(root, manifest)
        root.rename(destination)
    print(json.dumps({'verified_snapshot_files': len(owned), 'unavailable_records_at_source': unavailable}))


def restore(source, destination, runtime_dir=None):
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Choose a fresh directory, outside the snapshot')
    if runtime_dir is not None and not runtime_dir.is_absolute():
        raise ValueError('Runtime path must be absolute')
    runtime_dir = runtime_dir or destination
    manifest = json.loads((source / 'manifest.json').read_text())
    verify(source, manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=destination.parent) as stage:
        root = Path(stage) / 'restored'
        shutil.copytree(source, root)
        verify(root, manifest)
        mapping = {entry['source']: str(runtime_dir / relative)
                   for relative, entry in manifest['files'].items() if 'source' in entry}
        with closing(sqlite3.connect(root / DB)) as conn, conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('CREATE TEMP TABLE remap(old PRIMARY KEY,new NOT NULL)')
            conn.executemany('INSERT INTO remap VALUES (?,?)', mapping.items())
            for table in ('source_files', 'attachments'):
                conn.execute(f'''UPDATE {table} SET path=COALESCE((SELECT new FROM remap WHERE old={table}.path),
                                ?||id)''', (str(runtime_dir / 'unavailable')+'/',))
            conn.execute("UPDATE settings SET value='' WHERE key='source_folder'")
            conn.execute("""UPDATE settings SET value=COALESCE((SELECT new FROM remap WHERE old=settings.value),'')
                          WHERE key LIKE 'duplicate_trash:%'""")
            # Restored exercise data is retained. Live login tokens and cloud credentials are not used.
            for table in ('sessions', 'email_sessions'):
                if conn.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone():
                    conn.execute(f'DELETE FROM {table}')
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_outbox'").fetchone():
                conn.execute("UPDATE public_outbox SET state='cancelled',payload=NULL WHERE state IN ('queued','sending')")
                conn.execute('DELETE FROM public_links')
            profile = conn.execute("SELECT value FROM settings WHERE key='independent_public_origin'").fetchone()
            if profile:
                (root / '.pastpaper-public').write_text(profile[0])
            if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Restored SQLite integrity check failed')
            counts = {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('users', 'source_files', 'papers', 'questions', 'classrooms', 'class_assignments')}
        (root / 'manifest.json').unlink()
        root.rename(destination)
    print(json.dumps({'restored_counts': counts, 'relink_required':manifest['unavailable_records_at_source']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['snapshot','restore'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--runtime-dir', type=Path, help='absolute in-container path after restore')
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == 'snapshot':
        snapshot(args.source.resolve(), args.destination.resolve())
    else:
        restore(args.source.resolve(), args.destination.resolve(), args.runtime_dir)
