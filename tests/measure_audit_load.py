"""Reproduce the previous one-connection-per-request workload with per-route timings."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import math
import time
from urllib.request import build_opener, ProxyHandler, Request

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=39622)
parser.add_argument('--direct', type=int, help='Also support a loopback API comparison after checking the web fixture')
parser.add_argument('--transport', choices=('urllib','http-client'), default='urllib')
options = parser.parse_args()
if not all(39600 <= port <= 39699 for port in (options.port,options.direct or options.port)):
    parser.error('Use disposable loopback ports only')
origin = f'http://127.0.0.1:{options.port}'


def open_request(path, port, data=None, headers=None):
    opener = build_opener(ProxyHandler({}))
    return opener.open(Request(f'http://127.0.0.1:{port}'+path,data=data,headers=headers or {}),timeout=5)


with open_request('/',options.port) as response:
    if response.headers.get('X-PastPaper-Release') != 'audit-fixture':
        parser.error('Refusing unmarked server')
with open_request('/api/auth/login',options.port,
                  json.dumps({'email':'admin@example.test','password':'qa-only-password'}).encode(),
                  {'Content-Type':'application/json','Origin':origin}) as response:
    cookie = response.headers['Set-Cookie'].split(';')[0]
paths = ('/api/auth/me','/api/papers','/api/questions?limit=15','/api/classroom/classes')
port = options.direct or options.port


def sample(index):
    path = paths[index % len(paths)]
    start = time.perf_counter()
    error = False
    try:
        if options.transport == 'urllib':
            with open_request(path,port,headers={'Cookie':cookie}) as response:
                response.read()
        else:
            connection = http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.request('GET',path,headers={'Cookie':cookie,'Connection':'close'})
                response = connection.getresponse()
                error = response.status != 200
                response.read()
            finally:
                connection.close()
    except (OSError,http.client.HTTPException):
        error = True
    return path,(time.perf_counter()-start)*1000,error


def percentiles(values):
    values = sorted(values)
    return {f'p{int(p*100)}_ms':round(values[math.ceil(len(values)*p)-1],2) for p in (0.5,0.95,0.99)}


for concurrency in (1,5,20,50):
    started = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(sample, range(concurrency*5)))
    ended = time.time()
    per_route = defaultdict(list)
    for path,timing,_ in results:
        per_route[path].append(timing)
    errors = sum(error for _,_,error in results)
    print(json.dumps(dict(concurrency=concurrency,requests=len(results),started=started,ended=ended,
          **percentiles(t for _,t,_ in results),rps=round(len(results)/(ended-started),2),errors=errors,
          per_route={p:percentiles(v) for p,v in per_route.items()})),flush=True)
    if errors:
        raise SystemExit('Stopped before increasing load')
