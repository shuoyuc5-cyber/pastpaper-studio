"""Email migration and folder receipts against the real API with disposable data."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time

from fastapi.testclient import TestClient
import pymupdf

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='pastpaper-host-update-') as directory:
    os.environ['PASTPAPER_DATA_DIR']=directory
    from app import main
    admin={'username':'owner','password':'test-only-host-password'}
    old={'username':'existing-teacher','password':'test-only-teacher-password'}
    proxy={'x-forwarded-host':'192.168.254.91:39431','x-forwarded-for':'192.168.254.99','Origin':'http://192.168.254.91:39431'}
    with TestClient(main.app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as client:
        assert client.post('/api/auth/register',json=admin).status_code==200
        admin_cookies=dict(client.cookies)
        assert client.get('/api/auth/me').json()['local_host'] is True
        account=client.post('/api/admin/accounts',json=old).json()
        identity=account['id']
        assert client.put(f'/api/admin/accounts/{identity}/role',json={'role':'teacher'}).status_code==200
        salt='00'*16
        digest=hashlib.pbkdf2_hmac('sha256',old['password'].encode(),bytes.fromhex(salt),260000).hex()
        with main.connect() as conn:conn.execute('UPDATE users SET password_hash=? WHERE id=?',(salt+':'+digest,identity))
        client.cookies.clear()
        assert client.post('/api/auth/login',json=old).json()['user']['id']==identity
        assert client.get('/api/papers',headers=proxy).status_code==401
        assert client.get('/api/auth/me',headers=proxy).json()['user'] is None
        assert client.post('/api/auth/login',json=old,headers=proxy).status_code==400
        for email in ('abc','abc@','@gmail.com','a..b@example.test','name@invalid'):
            assert client.post('/api/auth/login',json={'email':email,'password':old['password']},headers=proxy).status_code==400
        assert client.put(f'/api/admin/accounts/{identity}/email',json={'email':'teacher@example.test'}).status_code==403
        client.cookies.clear();client.cookies.update(admin_cookies)
        assert client.put(f'/api/admin/accounts/{identity}/email',json={'email':'Teacher@Example.test'}).json()=={'email':'teacher@example.test'}
        assert client.post('/api/admin/accounts',json={**admin,'username':'duplicate','email':'TEACHER@example.test'}).status_code==409
        with main.connect() as conn:
            record=conn.execute('SELECT password_hash FROM users WHERE id=?',(identity,)).fetchone()
            assert record['password_hash'].startswith('scrypt-v1:') and old['password'] not in record['password_hash']
        client.cookies.clear()
        payload={'email':'teacher@example.test','password':old['password']}
        assert client.post('/api/auth/login',json={**payload,'password':'incorrect'},headers=proxy).status_code==401
        assert client.post('/api/auth/login',json={**payload,'email':'missing@example.test'},headers=proxy).status_code==401
        client_session=client.post('/api/auth/login',json=payload,headers=proxy)
        assert client_session.json()['user']=={'id':identity,'username':old['username'],'role':'teacher'}
        assert 'httponly' in client_session.headers['set-cookie'].lower()
        assert 'samesite=strict' in client_session.headers['set-cookie'].lower()
        remote_cookies=dict(client.cookies)
        assert client.get('/api/auth/device-access',headers=proxy).status_code==204
        assert client.get('/api/papers',headers=proxy).status_code==200
        assert client.get('/api/admin/accounts',headers=proxy).status_code==403
        assert client.get('/api/ai/models',headers=proxy).status_code==403
        client.cookies.clear();client.cookies.update(admin_cookies)
        assert client.put(f'/api/admin/accounts/{identity}/email',json={'email':'renamed@example.test'}).status_code==200
        client.cookies.clear();client.cookies.update(remote_cookies)
        assert client.get('/api/papers',headers=proxy).status_code==401
        client.cookies.clear();client.cookies.update(admin_cookies)

        def make_pdf(text):
            with pymupdf.open() as document:
                page=document.new_page()
                page.insert_text((45,90),text)
                return document.tobytes()

        def upload(name, relative, data):
            return client.post('/api/import/upload',params={'filename':name,'relative_path':relative},content=data,headers={'Content-Type':'application/pdf'})

        qp=make_pdf('1. A synthetic question for import verification.')
        ms=make_pdf('Synthetic mark scheme for the same paper.')
        assert upload('bad.pdf','Mock Folder/bad.pdf',b'%PDF-1.7\nmalformed').status_code==400
        assert upload('bad.pdf','Mock Folder/../bad.pdf',qp).status_code==400
        a=upload('0580_s26_qp_11.pdf','Mock Folder/Questions/0580_s26_qp_11.pdf',qp).json()
        b=upload('0580_s26_ms_11.pdf','Mock Folder/Answers/0580_s26_ms_11.pdf',ms).json()
        for _ in range(80):
            current=client.get('/api/import/status',params=[('ids',a['id']),('ids',b['id'])]).json()['files']
            if all(row['status']=='completed' for row in current):break
            time.sleep(.1)
        assert len(current)==2 and all(row['status']=='completed' for row in current), current
        assert client.get('/api/papers').json()['papers'][0]['pair_status']=='paired'
        assert upload('0580_s26_qp_11.pdf','Mock Folder/Questions/0580_s26_qp_11.pdf',qp).json()['id']==a['id']
        assert upload('0580_s26_qp_11.pdf','Mock Folder/Questions/0580_s26_qp_11.pdf',ms).status_code==409
        assert client.post('/api/import/upload?filename=single.pdf',content=make_pdf('Single import')).status_code==200
        client.cookies.clear()
        assert client.post('/api/auth/login',json=old).status_code==200
        assert client.get('/api/import/status',params={'ids':a['id']}).json()['files']==[]
    print('PASS: email validation, legacy migration and revocation, role preservation, folder scan receipts, QP/MS pairing, idempotency and single-file upload')
