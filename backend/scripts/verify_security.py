"""Security regressions in disposable storage; no real accounts are modified."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='studio-security-') as temp:
    os.environ['PASTPAPER_DATA_DIR']=temp+'/data'
    from app import main,studio,security
    import pymupdf
    from app.render_limits import check_render_size
    with TestClient(main.app) as client:
        credentials={'username':'owner','password':'temporary-security-password'}
        assert client.post('/api/auth/register',json=credentials).status_code==200
        owner_cookies=dict(client.cookies)
        with patch.object(pymupdf,'image_profile',return_value={'width':100000,'height':100000}),patch.object(pymupdf,'Pixmap') as decode:
            assert client.post('/api/attachments',content=b'fixture',headers={'Content-Type':'image/png'}).status_code==400
            decode.assert_not_called()
        assert client.get('/api/auth/me').headers['cache-control']=='private, no-store'
        assert client.get('/openapi.json').status_code==404
        assert client.get('/docs').status_code==404
        assert client.get('/api/health',headers={'Host':'attacker.example'}).status_code==403
        for headers in ({'sec-fetch-site':'cross-site'},{'sec-fetch-site':'same-site'},{'Origin':'https://attacker.example'}):
            assert client.post('/api/admin/invitations',json={},headers=headers).status_code==403
        assert client.post('/api/admin/invitations',json={},headers={'Origin':'http://testserver'}).status_code==200
        other={'username':'friend','password':'temporary-security-password'}
        assert client.post('/api/auth/register',json=other).status_code==403
        expired=client.post('/api/admin/invitations',json={}).json()['code']
        with main.connect() as conn:conn.execute('UPDATE invitations SET expires_at=?',(time.time()-1,))
        assert client.post('/api/auth/register',json={**other,'invite_code':expired}).status_code==403
        code=client.post('/api/admin/invitations',json={}).json()['code']
        friend=client.post('/api/auth/register',json={**other,'invite_code':code}).json()['user']['id']
        friend_cookies=dict(client.cookies)
        assert client.post('/api/auth/register',json={**other,'username':'another','invite_code':code}).status_code==403
        assert client.post('/api/admin/invitations',json={}).status_code==403
        assert client.post('/api/download',json={'source_id':'missing','urls':['https://example.com/a.pdf']}).status_code==403
        client.cookies.clear();client.cookies.update(owner_cookies)
        assert client.put(f'/api/admin/accounts/{friend}/ai-permissions',json={'enabled':False}).status_code==200
        client.cookies.clear();client.cookies.update(friend_cookies)
        assert client.get('/api/auth/me').json()['user'] is None
        assert client.get('/api/papers').status_code==401
        assert client.post('/api/auth/login',json=other).status_code==403
        assert client.post('/api/auth/login',content=b'x'*(256*1024+1),headers={'Content-Type':'application/json'}).status_code==413
        def chunks():
            for _ in range(5):yield b'x'*65536
        assert client.post('/api/auth/login',content=chunks(),headers={'Content-Type':'application/json'}).status_code==413
        security.ATTEMPTS.clear()
        for _ in range(10):assert client.post('/api/auth/login',json={**credentials,'password':'wrong-password'}).status_code==401
        assert client.post('/api/auth/login',json=credentials).status_code==429
    security.ATTEMPTS.clear()
    with TestClient(main.app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as proxy:
        headers={'x-forwarded-host':'192.168.1.50:3000','Origin':'http://192.168.1.50:3000','sec-fetch-site':'same-origin'}
        assert proxy.post('/api/auth/login',json=credentials,headers=headers).status_code==200
        assert proxy.post('/api/auth/login',json=credentials,headers={**headers,'Origin':'http://attacker.example'}).status_code==403
    check_render_size(pymupdf.Rect(0,0,595,842),3)
    try:check_render_size(pymupdf.Rect(0,0,100000,100000),1.7);raise AssertionError('huge PDF accepted')
    except ValueError:pass
    folder=Path(temp)/'uploads';path=folder/'a.pdf';u={'role':'student'}
    studio.store_upload(folder,path,b'original',u)
    try:studio.store_upload(folder,path,b'replacement',u);raise AssertionError('original overwritten')
    except HTTPException as e:assert e.status_code==409 and path.read_bytes()==b'original'
    with (folder/'quota').open('wb') as f:f.truncate(1024**3)
    try:studio.store_upload(folder,folder/'more.pdf',b'data',u);raise AssertionError('quota bypass')
    except HTTPException as e:assert e.status_code==413
    print('PASS: invitations/expiry/replay, account suspension, CSRF/host checks, no-store, body/stream limits, login throttling, PDF render limits, quota and overwrite protection')
