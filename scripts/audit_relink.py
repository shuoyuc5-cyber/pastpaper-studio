"""Inventory source gaps and optionally rehearse relinking in a newly restored copy."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

import audit_backup as backup


def read_catalog(database):
    with closing(backup.ro(database)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        rows = conn.execute('SELECT id,path,file_hash,status,owner_id,size_bytes FROM source_files').fetchall()
        settings = dict(conn.execute("SELECT key,value FROM settings WHERE key='source_folder' OR key LIKE 'duplicate_trash:%'"))
    return rows, settings


def availability(path):
    try:
        backup.stamp(path)
        return 'present'
    except PermissionError:
        return 'permission_denied'
    except (FileNotFoundError, NotADirectoryError):
        return 'path_missing'
    except (OSError, ValueError):
        return 'non_regular_or_other'


def stable_digest(path):
    before = backup.stamp(path)
    digest = backup.digest(path)
    if backup.stamp(path) != before:
        raise ValueError('File changed while it was checked')
    with path.open('rb') as source:
        if not re.fullmatch(rb'%PDF-[0-9]\.[0-9]', source.read(8)):
            raise ValueError('Expected PDF bytes')
    return digest


def association_counts(db_path, missing_ids):
    with closing(backup.ro(db_path)) as conn:
        conn.execute('CREATE TEMP TABLE missing(id PRIMARY KEY)')
        conn.executemany('INSERT INTO missing VALUES (?)', ((value,) for value in missing_ids))
        conn.execute('''CREATE TEMP TABLE affected_papers AS SELECT p.id FROM papers p
            WHERE p.qp_file_id IN (SELECT id FROM missing) OR p.ms_file_id IN (SELECT id FROM missing)''')
        conn.execute('CREATE TEMP TABLE affected_questions AS SELECT id,active FROM questions WHERE paper_id IN (SELECT id FROM affected_papers)')
        queries = {
            'papers': 'SELECT count(*) FROM affected_papers',
            'direct_qp_pointers': 'SELECT count(*) FROM papers WHERE qp_file_id IN (SELECT id FROM missing)',
            'direct_ms_pointers': 'SELECT count(*) FROM papers WHERE ms_file_id IN (SELECT id FROM missing)',
            'questions': 'SELECT count(*) FROM affected_questions',
            'active_questions': 'SELECT count(*) FROM affected_questions WHERE active=1',
            'bookmarks': 'SELECT count(*) FROM bookmarks WHERE question_id IN (SELECT id FROM affected_questions)',
            'attempts': 'SELECT count(*) FROM attempts WHERE question_id IN (SELECT id FROM affected_questions)',
            'practice_sessions': '''SELECT count(*) FROM practice_sessions s WHERE
                EXISTS(SELECT 1 FROM json_each(s.question_ids) WHERE value IN (SELECT id FROM affected_questions))''',
            'assignments_total': 'SELECT count(*) FROM class_assignments',
            'class_attempts_total': 'SELECT count(*) FROM class_attempts',
        }
        return {key: conn.execute(sql).fetchone()[0] for key, sql in queries.items()}


def add_candidates(database, label, wanted, candidates, manifest=None):
    rows, settings = read_catalog(database)
    for row in rows:
        key = (row['owner_id'], row['file_hash'])
        if key not in wanted:
            continue
        original = row['path']
        if row['status'] == 'deleted':
            original = settings.get('duplicate_trash:' + row['id'])
        if not original or not Path(original).is_absolute():
            continue
        if manifest is not None:
            path = manifest.get(original)
            if path is None:
                continue
        else:
            path = Path(original)
        if availability(path) == 'present':
            candidates[key].append((label, path))


def inventory(snapshot, live_data, historical):
    snapshot_db = snapshot / backup.DB
    rows, settings = read_catalog(snapshot_db)
    missing = [(row, availability(Path(row['path']))) for row in rows if row['status'] != 'deleted']
    missing = [(row, status) for row, status in missing if status != 'present']
    wanted = {(r['owner_id'], r['file_hash']) for r, _ in missing if r['owner_id'] and r['file_hash']}
    candidates = defaultdict(list)
    add_candidates(live_data / backup.DB, 'current_storage', wanted, candidates)
    for directory in [snapshot, *historical]:
        manifest_path = directory / 'manifest.json'
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        files = {}
        for relative, entry in manifest['files'].items():
            path = directory / relative
            if 'source' in entry and path.resolve().is_relative_to(directory):
                files[entry['source']] = path
        add_candidates(directory / backup.DB, 'backup', wanted, candidates, files)
    found, attempted = {}, {}
    disagreements = 0
    for key, options in candidates.items():
        for label, path in dict.fromkeys(options):
            if path not in attempted:
                try:
                    attempted[path] = stable_digest(path)
                except (OSError, ValueError):
                    attempted[path] = None
            if attempted[path] == key[1]:
                found[key] = (label, path)
                break
            disagreements += 1
    private_records = []
    reasons = Counter()
    match_types = Counter()
    watched = settings.get('source_folder')
    for row, condition in missing:
        key = (row['owner_id'], row['file_hash'])
        match = found.get(key)
        if condition == 'permission_denied':
            reason = 'permission_denied'
        elif condition != 'path_missing':
            reason = condition
        elif match:
            reason = 'moved_or_reimported_exact_bytes'
        else:
            reason = 'missing_no_verified_copy'
        reasons[reason] += 1
        if match:
            match_types[match[0]] += 1
        private_records.append(dict(id=row['id'], old_path=row['path'], reason=reason,
                                    candidate=str(match[1]) if match else None, sha256=row['file_hash']))
    result = dict(missing=len(missing), recoverable=sum(match_types.values()),
                  unresolved=len(missing)-sum(match_types.values()), causes=reasons,
                  candidates=match_types, rejected_candidate_checks=disagreements,
                  inside_current_watch=sum(bool(watched) and Path(r['path']).is_relative_to(watched) for r, _ in missing),
                  status_counts=Counter(r['status'] for r, _ in missing),
                  associations=association_counts(snapshot_db, [r['id'] for r, _ in missing]))
    return result, private_records


def rehearse(snapshot, destination, records):
    backup.restore(snapshot, destination)
    assets = destination / 'recovered_originals'
    assets.mkdir(mode=0o700)
    updated = 0
    with sqlite3.connect(destination / backup.DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        for row in records:
            if not row['candidate']:
                continue
            # Restore only existing catalog identities in the new copy. Keep the scanner away from this tree.
            name = str(uuid.UUID(row['id'])) + '.pdf'
            target = assets / name
            source = Path(row['candidate'])
            before = backup.stamp(source)
            if backup.digest(source,target) != row['sha256'] or backup.stamp(source) != before:
                raise ValueError('Backup candidate changed after the audit')
            changed = conn.execute("""UPDATE source_files SET path=?,size_bytes=?,mtime_ns=?
                WHERE id=? AND path=? AND file_hash=? AND status<>'deleted'""",
                (str(target),target.stat().st_size,target.stat().st_mtime_ns,row['id'],
                 str(destination/'unavailable'/row['id']),row['sha256']))
            if changed.rowcount != 1:
                raise ValueError('Catalog identity changed during the rehearsal')
            updated += 1
        assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    return updated


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('live_data',type=Path)
    parser.add_argument('private_report',type=Path)
    parser.add_argument('--historical',type=Path, action='append',default=[])
    parser.add_argument('--rehearse',type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    snapshot = args.snapshot.resolve()
    result, records = inventory(snapshot,args.live_data.resolve(),[p.resolve() for p in args.historical])
    with args.private_report.open('x') as output:
        json.dump(records,output)
    if args.rehearse:
        result['rehearsal_restored'] = rehearse(snapshot,args.rehearse.resolve(),records)
    print(json.dumps(result,sort_keys=True))
