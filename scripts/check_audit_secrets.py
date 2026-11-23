"""Fail on common credential shapes and forbidden data paths, without printing values."""
import argparse
import re
import subprocess
from pathlib import Path


def git(*args):
    return subprocess.check_output(('git', *args))


files = git('ls-files','-z').split(b'\0')
forbidden = re.compile(rb'(^|/)(?:backend/data/|node_modules/|\.venv/|\.env(?:\.[^/]+)?$)|\.(?:sqlite3?|db|p12|pfx|pem|key|pdf)$', re.I)
secrets = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,}|AKIA[A-Z0-9]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{45,}')
templates = {b'.env.example', b'deploy/fullstack/.env.example'}
matches = []
parser = argparse.ArgumentParser()
parser.add_argument('--history', action='store_true', help='check reachable Git blobs as well')
options = parser.parse_args()
for raw in filter(None, files):
    name = raw.decode('utf-8','surrogateescape')
    if (forbidden.search(raw) and raw not in templates) or (Path(name).is_file() and secrets.search(Path(name).read_bytes())):
        matches.append(name)
if matches:
    raise SystemExit('Review possible credential or runtime data files: '+', '.join(matches))
print(f'PASS: {len(files)-1} tracked paths scanned; no matches for configured patterns')

if options.history:
    count = 0
    entries = git('rev-list', '--objects', 'HEAD').splitlines()
    with subprocess.Popen(('git','cat-file','--batch'), stdin=subprocess.PIPE, stdout=subprocess.PIPE) as reader:
        for line in entries:
            oid, _, name = line.partition(b' ')
            reader.stdin.write(oid + b'\n')
            reader.stdin.flush()
            _, kind, length = reader.stdout.readline().split()
            size = int(length)
            if kind==b'blob' and size>16*1024*1024:
                raise SystemExit('Review oversized historical blob: '+oid.decode())
            content = reader.stdout.read(size)
            if len(content)!=size or reader.stdout.read(1)!=b'\n':
                raise SystemExit('Incomplete Git object scan')
            if kind!=b'blob':
                continue
            count += 1
            if (forbidden.search(name) and name not in templates) or secrets.search(content):
                matches.append(oid.decode())
        reader.stdin.close()
        if reader.wait():
            raise SystemExit('Unable to read Git objects')
    if matches:
        raise SystemExit('Review possible credential or runtime data objects: '+', '.join(matches))
    print(f'PASS: {count} reachable blobs scanned; no matches for configured patterns')
