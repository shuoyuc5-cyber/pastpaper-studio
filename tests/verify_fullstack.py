"""Exercise the independent full stack through its real Next HTTPS listener."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import sys
import time

import httpx
import pymupdf

from local_fullstack import ADMIN_EMAIL, ROOT, services

SYNTHETIC = 'Isolated-educator-demo-478'
UPDATED = 'Synthetic-new-password-695'
CLASS = '/api/classroom'
ADMIN = '/api/admin'
AUTH = '/api/auth'


def wait_for(check, timeout=35):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(.25)
    raise AssertionError('Expected state was not reached')


def call(client, route, expected=200, method='GET', payload=None, **kwargs):
    if isinstance(payload, bytes):
        response = client.request(method, route, content=payload, **kwargs)
    else:
        response = client.request(method, route, json=payload, **kwargs)
    assert response.status_code == expected, (method, route, expected, response.status_code,
                                               response.text[:250])
    return response


def obj(client, route, expected=200, method='GET', payload=None):
    return call(client, route, expected, method, payload).json()


def credential(email, password=SYNTHETIC, **extra):
    return {'email':email,'password':password,**extra}


def fixture(stem, *, scan=False, pages=1):
    with pymupdf.open() as doc:
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((55,80), f'1   {stem} [1]' if i==0 else f'{i+1}   Find a prime number. [1]', fontsize=13)
        if scan:
            images = [page.get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png') for page in doc]
            with pymupdf.open() as raster:
                for png in images:
                    page = raster.new_page()
                    page.insert_image(page.rect, stream=png)
                return raster.tobytes(deflate=True)
        return doc.tobytes(deflate=True)


def messages(root, recipient, subject):
    results = []
    for path in sorted((root/'mail').glob('*.eml')):
        msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        if str(msg['To']) == recipient and str(msg['Subject']) == subject:
            results.append(msg.get_body().get_content())
    return results


def link(root, recipient, subject='Set up your PastPaper Studio account'):
    message = wait_for(lambda: messages(root,recipient,subject))[0]
    return re.search(r'#account=([A-Za-z0-9_-]{43})',message)[1]


def verify(root, env, seed, password):
    import hmac
    import os
    origin = env['PASTPAPER_PUBLIC_ORIGIN']
    tls = ssl.create_default_context(cafile=env['PASTPAPER_TEST_TLS_CERT'])
    stack = ExitStack()
    def client():
        return stack.enter_context(httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=15,
                                                headers={'Origin':origin, 'X-Studio-Language':'en'}))

    def upload(actor, name, contents, status=200, path=None):
        params = {'filename':name}
        if path:
            params['relative_path'] = path
        response = call(actor, '/api/import/upload', status, 'POST', contents, params=params)
        return response.json().get('id')

    def process(actor, identity, state):
        return wait_for(lambda: any(row['status']==state for row in
            call(actor, '/api/import/status', params={'ids':identity}).json()['files']))

    def otp(counter):
        digest = hmac.digest(seed,counter.to_bytes(8,'big'),'sha1')
        i = digest[-1]&15
        return f'{(int.from_bytes(digest[i:i+4],"big")&0x7fffffff)%1000000:06d}'

    with stack:
        wrong = root/'unrelated-data'
        wrong.mkdir()
        (wrong/'.pastpaper-public').write_text(origin)
        with sqlite3.connect(wrong/'pastpaper_studio.sqlite3') as conn:
            conn.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
        invalid = subprocess.run([sys.executable,'-c','from app import main'],capture_output=True,text=True,
                                 env={**env,'PYTHONPATH':str(ROOT/'backend'),'PASTPAPER_DATA_DIR':str(wrong)})
        assert invalid.returncode and 'refuses databases from other profiles' in invalid.stderr
        anonymous, admin, teacher, other, student, peer = [client() for _ in range(6)]
        teacher_email, second_email = 'teacher@example.test','other@example.test'
        student_email, peer_email = 'student@example.test','peer@example.test'
        with services(root, env) as processes:
            assert b'PastPaper Studio' in call(anonymous,'/').content
            call(anonymous,'/device/index.html',302)
            call(anonymous,'/api/papers',401)
            call(anonymous,AUTH+'/register',404,'POST',{})
            inventory = subprocess.check_output([sys.executable,'-c',
                "import json;from fastapi.routing import APIRoute;from app.main import app;"
                "print(json.dumps([(r.path,sorted(r.methods)) for r in app.routes if isinstance(r,APIRoute)]))"],
                env={**env,'PYTHONPATH':str(ROOT/'backend')},text=True)
            exposed = {AUTH+'/login',AUTH+'/me',AUTH+'/public-register',AUTH+'/forgot-password',
                       AUTH+'/complete-link','/api/health'}
            host_only = {AUTH+'/register','/api/settings/source-folder','/api/settings/select-folder','/api/scan'}
            restricted = 0
            for template, methods in json.loads(inventory):
                if template in exposed:
                    continue
                route = re.sub(r'\{[^}]+\}','unknown',template)
                for method in methods:
                    call(anonymous,route,404 if template in host_only else 401,method)
                    restricted += 1
            print(f'PASS authorization inventory | {restricted} route-method pairs deny anonymous requests',flush=True)
            call(anonymous,AUTH+'/login',403,'POST',credential(ADMIN_EMAIL,password),
                 headers={'Origin':'https://attacker.example.test','X-Forwarded-For':'127.0.0.1'})
            plain = httpx.get('http://127.0.0.1:'+env['PASTPAPER_BACKEND_PORT']+'/api/auth/me',
                              headers={'Host':origin.removeprefix('https://')},trust_env=False)
            assert plain.status_code==403
            call(anonymous,'/',403,headers={'Host':'outside.example.test'})
            call(anonymous,AUTH+'/login',428,'POST',credential(ADMIN_EMAIL,password))
            code = otp(int(time.time())//30)
            response = call(admin,AUTH+'/login',200,'POST',credential(ADMIN_EMAIL,password,otp=code))
            cookie = response.headers['set-cookie'].lower()
            assert all(value in cookie for value in ('__host-studio_session=','httponly','secure','samesite=strict','path=/'))
            assert 'domain=' not in cookie
            assert response.headers['x-frame-options']=='DENY'
            assert response.headers['cache-control']=='private, no-store'
            call(anonymous,AUTH+'/login',401,'POST',credential(ADMIN_EMAIL,password,otp=code))
            assert obj(admin,ADMIN+'/host-status')['database']
            call(admin,'/api/settings/select-folder',404,'POST',{})
            call(admin,'/api/ai/models',403)
            print('PASS 01 | Actual HTTPS, origin/Host binding, MFA and replay, admin-only setup and private AI boundary',flush=True)

            people = {}
            for email in (teacher_email,second_email,peer_email):
                person = obj(admin,ADMIN+'/accounts',201,'POST',credential(email,username=email.split('@')[0]))
                people[email] = person['id']
            call(teacher,AUTH+'/login',403,'POST',credential(teacher_email))
            for email in (teacher_email,second_email):
                obj(admin,f'{ADMIN}/accounts/{people[email]}/role',200,'PUT',{'role':'teacher'})
            for actor,email in ((teacher,teacher_email),(other,second_email),(peer,peer_email)):
                token = link(root,email)
                obj(anonymous,AUTH+'/complete-link',200,'POST',{'token':token,'password':SYNTHETIC})
                call(anonymous,AUTH+'/complete-link',400,'POST',{'token':token,'password':SYNTHETIC})
                obj(actor,AUTH+'/login',200,'POST',credential(email))
            invite = obj(admin,ADMIN+'/invitations',200,'POST')['code']
            request = {'username':'Invited student','email':student_email,'invite_code':invite}
            call(anonymous,AUTH+'/public-register',202,'POST',request)
            assert obj(anonymous,AUTH+'/me')['user'] is None
            obj(anonymous,AUTH+'/complete-link',200,'POST',{'token':link(root,student_email),'password':SYNTHETIC})
            people[student_email] = obj(student,AUTH+'/login',200,'POST',credential(student_email))['user']['id']
            call(student,ADMIN+'/accounts',403)
            call(other,ADMIN+'/accounts',403)
            call(student,'/device/index.html')
            assert len(obj(admin,ADMIN+'/role-audit')['events'])==2
            print('PASS 02 | Admin role management, invites, verified inbox, student and teacher authentication',flush=True)

            room = obj(teacher,CLASS+'/classes',201,'POST',{'name':'QA algebra','subject':'Mathematics'})
            path = CLASS+'/classes/'+room['id']
            call(student,CLASS+'/classes',403,'POST',{'name':'Denied','subject':'Math'})
            call(other,path+'/members',404)
            for actor,email in ((student,student_email),(peer,peer_email)):
                joined = obj(actor,CLASS+'/join',200,'POST',{'code':room['join_code']})
                assert joined['status']=='pending'
                obj(teacher,path+'/members/'+people[email],200,'PUT')
            assert len(obj(teacher,path+'/members')['members'])==2

            qp_name, ms_name = '0580_s26_qp_11.pdf','0580_s26_ms_11.pdf'
            qp = fixture('Find the probability of a six.')
            ms = fixture('1/6 B1')
            call(student,'/api/import/upload?filename=test.pdf',403,'POST',qp)
            upload(teacher,qp_name,qp,400,path='../'+qp_name)
            upload(teacher,'bad.pdf',b'PNG',400)
            broken = upload(teacher,'broken.pdf',b'%PDF-1.7\nthis is an invalid document')
            call(teacher,'/api/files/'+broken,404)
            qid = upload(teacher,qp_name,qp,path='synthetic/set/'+qp_name)
            mid = upload(teacher,ms_name,ms,path='synthetic/answer/'+ms_name)
            process(teacher,qid,'completed')
            process(teacher,mid,'completed')
            process(teacher,broken,'failed')
            assert upload(teacher,qp_name,qp,path='synthetic/set/'+qp_name)==qid
            paper = wait_for(lambda: next((p for p in obj(teacher,'/api/papers?q=0580')['papers']
                                           if p['pair_status']=='paired'),None))
            assert paper['qp_file_id']==qid and paper['ms_file_id']==mid
            assert call(teacher,'/api/files/'+qid).content==qp
            assert call(teacher,'/api/files/'+mid).content==ms
            assert call(teacher,'/api/files/'+qid+'/pages/1').content.startswith(b'\x89PNG')
            call(other,'/api/files/'+qid,404)
            call(student,'/api/files/'+qid,404)
            call(teacher,'/api/files/'+qid,416,headers={'Range':'bytes=0-3,8-13'})
            assert call(teacher,'/api/files/'+qid,206,headers={'Range':'bytes=0-7'}).content==qp[:8]
            question = wait_for(lambda: obj(teacher,'/api/questions?subject_code=0580&q=probability')['questions'])[0]
            assert call(teacher,f"/api/questions/{question['id']}/image").content.startswith(b'\x89PNG')
            share = '/api/papers/'+paper['id']+'/sharing'
            call(other,share,404,'PUT',{'visibility':'public','rights_confirmed':True})
            obj(teacher,share,200,'PUT',{'visibility':'public','rights_confirmed':True})
            assert call(student,'/api/files/'+qid).headers['cache-control']=='private, no-store'
            assert obj(student,'/api/questions?q=probability')['total']==1
            obj(student,f"/api/questions/{question['id']}/bookmark",200,'PUT',{'saved':True,'note':'my study note'})
            assert obj(student,'/api/questions?saved=true')['total']==1 and obj(peer,'/api/questions?saved=true')['total']==0
            built = obj(teacher,'/api/builder/auto',200,'POST',{'count':1,'include_pending':True,'q':'probability'})
            assert built
            preview = obj(teacher,'/api/builder/preview',200,'POST',{'question_ids':[question['id']]})
            assert preview['questions'][0]['id']==question['id']
            edit = {key:question[key] for key in ('label','stem','tags','difficulty','segments','context_segments','ms_segments')}
            edit['review_status'] = 'confirmed'
            obj(teacher,f"/api/questions/{question['id']}",200,'PUT',edit)
            assert call(teacher,'/api/builder/export?kind=qp',200,'POST',{'items':[{'question_id':question['id']}]}).content.startswith(b'%PDF-')
            assert obj(teacher,path+'/generate',200,'POST',{'count':1,'subject_code':'0580'})['questions']
            obj(teacher,share,200,'PUT',{'visibility':'private'})
            call(student,'/api/files/'+qid,404)
            obj(teacher,share,200,'PUT',{'visibility':'public','rights_confirmed':True})
            replacement = fixture('Find the probability of rolling a two.')
            obj(teacher,'/api/import/'+qid+'/replace',200,'PUT',replacement)
            call(student,'/api/files/'+qid,404)
            call(student,'/api/files/'+mid,404)
            process(teacher,qid,'completed')
            assert call(teacher,'/api/files/'+qid).content==replacement
            call(student,'/api/files/'+qid,404)
            obj(teacher,share,200,'PUT',{'visibility':'public','rights_confirmed':True})
            assert call(student,'/api/files/'+qid).content==replacement
            scan_id = upload(teacher,'0580_s26_qp_12.pdf',fixture('Read the number twelve and explain its factors.',scan=True))
            process(teacher,scan_id,'completed')
            wait_for(lambda: obj(teacher,'/api/questions?q=factors')['questions'])
            assert list((Path(env['PASTPAPER_DATA_DIR'])/'ocr').glob('*.json'))
            metadata = obj(teacher,'/api/files/'+scan_id+'/metadata')
            assert metadata['pages']==1
            print('PASS 03 | PDF queue, nested path, corruption and traversal, QP/MS, direct image, OCR, search, saved state, preview, revoke/replace',flush=True)

            questions = [
                {'text':'Select 2','kind':'single','marks':1,'options':['2','3'],'accepted':['0']},
                {'text':'Choose even numbers','kind':'multiple','marks':4,'options':['2','4','5'],'accepted':['0','1'],'partial_credit':True},
                {'text':'Seven is odd','kind':'boolean','marks':1,'accepted':['true']},
                {'text':'Name a color','kind':'fill','marks':2,'accepted':['Blue']},
                {'text':'Approximate root','kind':'number','marks':2,'accepted':['1.414'],'tolerance':.01},
                {'text':'Explain why','kind':'short','marks':3},
            ]
            draft = {'title':'Algebra practice','questions':questions,'rules':{'leaderboard':True,'reveal_answers':True}}
            assignment = obj(teacher,path+'/assignments',201,'POST',draft)
            work = CLASS+'/assignments/'+assignment['id']
            call(other,work+'/publish',404,'POST')
            plain_pdf = fixture('First classroom question')
            call(teacher,path+'/document-import',200,'POST',plain_pdf,headers={'Content-Type':'application/pdf'})
            obj(teacher,work+'/publish',200,'POST')
            obj(teacher,work+'/publish',200,'POST')
            wait_for(lambda: messages(root,student_email,'New PastPaper Studio assignment'))
            assert len(messages(root,student_email,'New PastPaper Studio assignment'))==1
            outcomes = []
            for actor in (student,peer):
                attempt = obj(actor,work+'/attempts',200,'POST')
                assert not any('accepted' in row for row in attempt['questions'])
                outcomes.append(work+'/attempts/'+attempt['id'])
            call(peer,outcomes[0],404,'PUT',{'revision':0,'answers':{}})
            call(student,work+'/submissions',403)
            data = {'revision':0,'answers':{0:'0',1:['0'],2:'false',3:'blue',4:'1.42'}}
            saved = obj(student,outcomes[0],200,'PUT',data)
            call(student,outcomes[0],409,'PUT',data)
            data['revision'] = saved['revision']
            with ThreadPoolExecutor(3) as pool:
                a = pool.submit(obj,student,outcomes[0]+'/submit',200,'POST',data)
                b = pool.submit(obj,student,outcomes[0]+'/submit',200,'POST',data)
                c = pool.submit(obj,peer,outcomes[1]+'/submit',200,'POST',{'revision':0,'answers':{}})
                student_result = a.result()
                assert student_result==b.result() and c.result()['metrics']['marks']==0
            assert [student_result['grades'][str(i)]['marks'] for i in range(6)]==[1,2,0,2,2,None]
            grade = work+'/submissions/'+student_result['id']+'/grades/5'
            call(student,grade,403,'PUT',{'marks':2})
            call(other,grade,404,'PUT',{'marks':2})
            obj(teacher,grade,200,'PUT',{'marks':2,'feedback':'Use one more step.'})
            assert obj(teacher,path+'/analytics')['assignments'][0]['completed']==2
            assert obj(student,work+'/leaderboard')['ranking']
            assert obj(student,work)['attempts'][0]['grades']['5']['marks']==2
            call(other,path+'/archive',404,'PUT',{})
            obj(teacher,path+'/archive',200,'PUT',{})
            call(anonymous,AUTH+'/forgot-password',202,'POST',{'email':'absent@example.test'})
            call(student,AUTH+'/forgot-password',202,'POST',{'email':student_email})
            reset = link(root,student_email,'Reset your PastPaper Studio password')
            obj(anonymous,AUTH+'/complete-link',200,'POST',{'token':reset,'password':UPDATED})
            call(anonymous,AUTH+'/complete-link',400,'POST',{'token':reset,'password':UPDATED})
            call(student,'/api/papers',401)
            call(student,AUTH+'/login',401,'POST',credential(student_email))
            obj(student,AUTH+'/login',200,'POST',credential(student_email,UPDATED))
            print('PASS 04 | Scoped class and assignment, notifications, draft conflicts, concurrent submit, all answer types, marks, feedback, ranking, archival and reset',flush=True)

            processes['worker'].terminate()
            processes['worker'].wait(timeout=15)
            abandoned = upload(teacher,'0580_s26_qp_13.pdf',fixture('Cancelled job.'))
            obj(teacher,'/api/import/'+abandoned+'/cancel',200,'POST')
            process(teacher,abandoned,'cancelled')
            queued = upload(teacher,'0580_s26_qp_14.pdf',fixture('A queued file survives a restart.'))
            process(teacher,queued,'waiting')
            assert obj(admin,ADMIN+'/public-health')['queued_pdfs']==1
            call(student,ADMIN+'/public-health',403)

        with services(root, env) as workers:
            process(teacher,queued,'completed')
            process(teacher,abandoned,'cancelled')
            assert obj(teacher,work+'/submissions')['submissions']
            assert obj(student,AUTH+'/me')['user']['role']=='student'
            assert call(student,'/api/files/'+qid).content==replacement
            from measure_fullstack import measure
            assert obj(admin,ADMIN+'/public-health')['queued_pdfs']==0
            measure(root, env, tls, student, teacher, qid, work, workers)
            if os.getenv('PASTPAPER_TEST_EXTENDED_LOAD')=='1':
                from measure_fullstack import extended
                extended(root, teacher, student, upload, process, fixture, path, work, call, obj)

        snapshot, restored = root/'snapshot',root/'restored'
        for action, src,dst in [('snapshot',Path(env['PASTPAPER_DATA_DIR']),snapshot),('restore',snapshot,restored)]:
            subprocess.run([sys.executable, str(ROOT/'scripts/audit_backup.py'),action,str(src),str(dst)],check=True)
        (restored/'.pastpaper-public').write_text(origin)
        with sqlite3.connect(restored/'pastpaper_studio.sqlite3') as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert db.execute('SELECT COUNT(*) FROM class_attempts').fetchone()[0]==(
                26 if os.getenv('PASTPAPER_TEST_EXTENDED_LOAD')=='1' else 2)
            assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        with services(root, {**env, 'PASTPAPER_DATA_DIR':str(restored)}):
            call(student,'/api/papers',401)
            obj(student,AUTH+'/login',200,'POST',credential(student_email,UPDATED))
            assert call(student,'/api/files/'+qid).content==replacement
            assert obj(student,work)['attempts'][0]['grades']['5']['marks']==2
        print('PASS 05 | Worker stopped with queued/cancelled jobs, services restarted; checksummed snapshot restored and exercised over HTTPS',flush=True)
        browser_package = os.getenv('PASTPAPER_TEST_PLAYWRIGHT')
        if browser_package:
            browser_env = dict(os.environ, PASTPAPER_TEST_ORIGIN=origin, PASTPAPER_TEST_EVIDENCE=str(root),
                               PASTPAPER_TEST_STUDENT_PASSWORD=UPDATED)
            (root/'browser-fixtures').mkdir()
            (root/'browser-fixtures'/'0580_s26_qp_21.pdf').write_bytes(fixture('Browser fixture: find a multiple.'))
            (root/'browser-fixtures'/'unused.txt').write_text('ignore this test file')
            browser_env['PASTPAPER_TEST_TEACHER_PASSWORD'] = SYNTHETIC
            with services(root,env):
                subprocess.run(['node',str(ROOT/'tests/fullstack-browser.mjs')],env=browser_env,check=True)
        else:
            print('NOT TESTED | Browser automation was not enabled (PASTPAPER_TEST_PLAYWRIGHT).',flush=True)
    (root/'verified.json').write_text(json.dumps({'core_scenarios':5,'browser':bool(browser_package)}))
