"""Bounded read load probe. Dedicated loopback fixture only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
from urllib.request import build_opener, ProxyHandler, Request

p = argparse.ArgumentParser()
p.add_argument('--port', type=int, default=39603)
p.add_argument('--rounds', type=int, choices=range(1, 6), default=5)
args = p.parse_args()
if not 39600 <= args.port <= 39699:
    p.error('Use an isolated fixture port from 39600 to 39699.')
origin = f'http://127.0.0.1:{args.port}'


def open_request(path, data=None, headers=None):
    opener = build_opener(ProxyHandler({}))
    return opener.open(Request(origin + path, data=data, headers=headers or {}), timeout=5)


with open_request('/') as response:
    if response.headers.get('X-PastPaper-Release') != 'audit-fixture':
        p.error('Refusing to test an endpoint without the audit fixture marker.')
with open_request('/api/auth/login',
                  json.dumps({'email':'admin@example.test','password':'qa-only-password'}).encode(),
                  {'Content-Type':'application/json','Origin':origin}) as response:
    cookie = response.headers['Set-Cookie'].split(';')[0]
paths = ('/api/auth/me','/api/papers','/api/questions?limit=15','/api/classroom/classes')


def sample(i):
    t = time.perf_counter()
    try:
        with open_request(paths[i % len(paths)], headers={'Cookie':cookie}) as response:
            response.read()
        return (time.perf_counter()-t)*1000,False
    except OSError:
        return (time.perf_counter()-t)*1000,True


for users in (1,5,20,50):
    elapsed = time.perf_counter()
    with ThreadPoolExecutor(max_workers=users) as pool:
        results = list(pool.map(sample, range(users*args.rounds)))
    timings = sorted(x for x,_ in results)
    failures = sum(f for _,f in results)
    print(json.dumps({'concurrency':users,'requests':len(results),'p95_ms':round(timings[math.ceil(len(timings)*.95)-1],1),
                      'rps':round(len(results)/(time.perf_counter()-elapsed),1),'failures':failures}),flush=True)
    if failures:
        raise SystemExit('Stopped before increasing load.')
