"""Consistent loopback HTTPS workload on a synthetic already-signed-in dataset."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import shutil
import subprocess
import threading
import time

import httpx


def measure(root, env, tls, student, teacher, file_id, assignment, processes):
    base = env['PASTPAPER_PUBLIC_ORIGIN']
    def benchmark(name, users, requests, cookie):
        with httpx.Client(base_url=base, verify=tls, trust_env=False, timeout=15, cookies=cookie,
                          limits=httpx.Limits(max_connections=users,max_keepalive_connections=users)) as web:
            for route in requests:
                assert web.get(route).status_code==200
            latencies, errors = [], []
            start = time.monotonic()
            def call(i):
                before = time.monotonic()
                try:
                    status = web.get(requests[i % len(requests)]).status_code
                except httpx.HTTPError:
                    status = 0
                return (time.monotonic() - before)*1000, status
            with ThreadPoolExecutor(users) as pool:
                for elapsed, status in pool.map(call, range(max(40, users*8))):
                    latencies.append(elapsed)
                    if status!=200:
                        errors.append(status)
            throughput = len(latencies)/(time.monotonic()-start)
        latencies.sort()
        point = lambda q: round(latencies[math.ceil(len(latencies)*q)-1],2)
        result = dict(workload=name, concurrency=users, requests=len(latencies), p50_ms=point(.5),
                      p95_ms=point(.95), p99_ms=point(.99), req_s=round(throughput,2), errors=len(errors))
        print('LOAD',json.dumps(result),flush=True)
        return result

    stop=threading.Event()
    samples=[]
    def sample():
        pids=','.join(str(proc.pid) for proc in processes.values())
        while not stop.is_set():
            values=subprocess.check_output(['ps','-p',pids,'-o','%cpu=,rss='],text=True).splitlines()
            rows=[tuple(map(float,line.split())) for line in values if line.strip()]
            if rows:
                samples.append((sum(row[0] for row in rows),sum(row[1] for row in rows)/1024))
            stop.wait(.2)
    sampler=threading.Thread(target=sample,daemon=True)
    # A slim Linux image may omit ps. A missing sampler must be visible in the report.
    if shutil.which('ps'):
        sampler.start()
    readings = [benchmark('auth/search/paper/assignment',users,
                  ['/api/auth/me','/api/questions?q=probability','/api/papers?q=0580',assignment], student.cookies)
                for users in (1,5,10,20,50)]
    if readings[-1]['errors']==0 and readings[-1]['p95_ms']<=500:
        readings.append(benchmark('auth/search/paper/assignment',100,
                  ['/api/auth/me','/api/questions?q=probability','/api/papers?q=0580',assignment], student.cookies))
    for name, path in (('download','/api/files/'+file_id),('render','/api/files/'+file_id+'/pages/1')):
        readings.append(benchmark(name,1,[path],teacher.cookies))
    stop.set()
    if sampler.is_alive():
        sampler.join(timeout=2)
    resource = {'peak_ps_cpu_pct':max((row[0] for row in samples),default=None),
                'peak_combined_rss_mib':max((round(row[1],1) for row in samples),default=None),
                'resource_samples':len(samples)}
    print('RESOURCES',json.dumps(resource),flush=True)
    (root/'load.json').write_text(json.dumps({'requests':readings,'resources':resource},indent=2))


def extended(root, teacher, student, upload, process, fixture, class_path, assignment, call, obj):
    import pymupdf
    started = time.monotonic()
    scan = fixture('Large raster exercise. Evaluate the expression.',scan=True,pages=12)
    source = upload(teacher,'0580_s26_qp_15.pdf',scan)
    accepted = time.monotonic()
    latencies = []
    for _ in range(36):
        request = time.monotonic()
        obj(student,assignment)
        latencies.append((time.monotonic()-request)*1000)
        time.sleep(.12)
    process(teacher,source,'completed')
    ready = time.monotonic()
    wait_until=time.monotonic()+75
    while not obj(teacher,'/api/questions?paper_id='+next(
        paper['id'] for paper in obj(teacher,'/api/papers')['papers'] if paper['qp_file_id']==source))['total']:
        if time.monotonic()>wait_until:
            raise AssertionError('Extended OCR indexing did not complete')
        time.sleep(.5)
    indexed=time.monotonic()
    # 16 MiB of deterministically generated, syntactically valid PDF bytes.
    import random
    rng = random.Random(20261115)
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((55,80),'1    A PDF with an embedded binary block. [1]')
        doc.embfile_add('synthetic.bin',rng.randbytes(16*1024*1024))
        big = doc.tobytes()
    before = time.monotonic()
    big_id=upload(teacher,'0580_s26_qp_16.pdf',big)
    upload_sec=time.monotonic()-before
    process(teacher,big_id,'completed')
    before=time.monotonic()
    assert call(teacher,'/api/files/'+big_id).content==big
    obj(teacher,class_path+'/archive?archived=false',200,'PUT',{})
    attempts = []
    for i in range(24):
        draft = {'title':f'Write load fixture {i+1}',
                 'questions':[{'text':'Is seven odd?','kind':'boolean','marks':1,'accepted':['true']}]}
        info = obj(teacher,class_path+'/assignments',201,'POST',draft)
        route = '/api/classroom/assignments/'+info['id']
        obj(teacher,route+'/publish',200,'POST')
        attempt = obj(student,route+'/attempts',200,'POST')
        attempts.append(route+'/attempts/'+attempt['id']+'/submit')
    started_writes = time.monotonic()
    def submit(route):
        start = time.monotonic()
        score = obj(student,route,200,'POST',{'revision':0,'answers':{0:'true'}})
        assert score['metrics']['marks']==1
        return (time.monotonic()-start)*1000
    with ThreadPoolExecutor(10) as pool:
        writes=sorted(pool.map(submit,attempts))
    write_seconds = time.monotonic()-started_writes
    result={'submissions':len(attempts),'submission_p95_ms':round(writes[math.ceil(len(writes)*.95)-1],2),
            'submission_req_s':round(len(attempts)/write_seconds,2),'write_concurrency':10,'submission_errors':0,
            'raster_pages':12,'raster_bytes':len(scan),'upload_sec':round(accepted-started,3),
            'registered_pdf_sec':round(ready-started,3),'all_ocr_and_index_sec':round(indexed-started,3),
            'while_processing_assignment_p95_ms':round(sorted(latencies)[math.ceil(len(latencies)*.95)-1],2),
            'large_bytes':len(big),'large_upload_sec':round(upload_sec,3),
            'large_download_sec':round(time.monotonic()-before,3)}
    print('EXTENDED',json.dumps(result),flush=True)
    (root/'extended.json').write_text(json.dumps(result,indent=2))
