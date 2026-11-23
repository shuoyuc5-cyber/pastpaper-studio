"""Probe a disposable Host release over its real Next.js and FastAPI listeners."""
import argparse
import http.client
import json
import time
from urllib.parse import quote

import pymupdf

parser = argparse.ArgumentParser()
parser.add_argument('phase', choices=('seed','check'))
parser.add_argument('revision')
parser.add_argument('--port',type=int,default=39643)
parser.add_argument('--lan-host', help='Use this LAN Host and origin over the QA loopback socket')
options = parser.parse_args()
if not 39600 <= options.port <= 39699:
    parser.error('Use a disposable QA port')


def call(path, *, method='GET', payload=None, cookie=None, host=None):
    host = host or '127.0.0.1'
    origin = f'http://{host}:{options.port}'
    headers = {'Origin':origin,'Host':f'{host}:{options.port}'}
    if isinstance(payload,dict):
        payload=json.dumps(payload)
        headers['Content-Type']='application/json'
    elif payload:
        headers['Content-Type']='application/pdf'
    if cookie:
        headers['Cookie']=cookie
    connection=http.client.HTTPConnection('127.0.0.1',options.port,timeout=10)
    try:
        connection.request(method,path,body=payload,headers=headers)
        response=connection.getresponse()
        return response.status, dict((k.lower(),v) for k,v in response.getheaders()), response.read()
    finally:
        connection.close()


def result(path, status=200, **kwargs):
    actual, _, data=call(path,**kwargs)
    assert actual==status,(path,actual,status)
    return json.loads(data) if data else None


def credential(role):
    return {'email':f'{role}@example.test','username':role,'password':'synthetic-release-demo-only'}


def login(role, host=None):
    status, headers, _=call('/api/auth/login',method='POST',payload=credential(role),host=host)
    assert status==200,(role,status)
    return headers['set-cookie'].split(';',1)[0]


def wait_for(fn):
    stop=time.monotonic()+35
    while time.monotonic()<stop:
        value=fn()
        if value:
            return value
        time.sleep(.4)
    raise AssertionError('fixture state did not become ready')


status, headers, page=call('/')
assert status==200 and headers.get('x-pastpaper-release')==options.revision and b'PastPaper Studio' in page
assert result('/api/health')['status']=='ok'
assert result('/api/papers',401)
if options.phase=='seed':
    result('/api/auth/register',method='POST',payload=credential('admin'))
admin=login('admin')
if options.phase=='seed':
    result('/api/admin/accounts',201,method='POST',payload=credential('student'),cookie=admin)
student=login('student',options.lan_host)
assert result('/api/auth/me',cookie=student,host=options.lan_host)['user']['role']=='student'
assert result('/api/admin/accounts',403,cookie=student,host=options.lan_host)
assert result('/api/ai/models',403,cookie=student,host=options.lan_host)
names = {'qp':'0580_s26_qp_11.pdf','ms':'0580_s26_ms_11.pdf'}
if options.phase=='seed':
    for kind,name in names.items():
        with pymupdf.open() as doc:
            page=doc.new_page()
            page.insert_text((60,80),'1 Find the probability of a six. [1]' if kind=='qp' else '1 1/6 B1')
            data=doc.tobytes()
        result('/api/import/upload?filename='+quote(name),method='POST',payload=data,cookie=admin)

paper=wait_for(lambda:next((p for p in result('/api/papers?q=0580',cookie=admin)['papers']
                             if p['paper_number']=='11' and p['pair_status']=='paired'),None))
if options.phase=='seed':
    assert result('/api/papers?q=0580',cookie=student,host=options.lan_host)['papers']==[]
    result('/api/papers/'+paper['id']+'/sharing',method='PUT',
           payload={'visibility':'public','rights_confirmed':True},cookie=admin)
    result('/api/catalog/index?paper_id='+paper['id'],method='POST',cookie=admin)
assert result('/api/papers?q=0580',cookie=student,host=options.lan_host)['papers'][0]['id']==paper['id']
for column in ('qp_file_id','ms_file_id'):
    status, _, data=call('/api/files/'+paper[column],cookie=student,host=options.lan_host)
    assert status==200 and data.startswith(b'%PDF-')
    status, _, data=call('/api/files/'+paper[column]+'/pages/1',cookie=admin)
    assert status==200 and data.startswith(b'\x89PNG')
query = '/api/questions?subject_code=0580&q=probability&limit=15'
questions = wait_for(lambda: result(query,cookie=admin)['questions'])
assert 'probability' in questions[0]['stem']
assert result(query,cookie=student,host=options.lan_host)['total'] == 1
assert result(query+'&saved=true',cookie=admin)['total'] == 0
assert result(query+'&mistakes=true',cookie=admin)['total'] == 0
print(f'PASS: {options.phase} {options.revision}. Login, student boundaries, upload/pair, sharing, search and PDF renders.')
