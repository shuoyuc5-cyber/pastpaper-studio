"""V3 policy checks, using a temporary database and no AI provider traffic."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='studio-v3-security-') as temp:
    os.environ['PASTPAPER_DATA_DIR'] = temp
    os.environ['PASTPAPER_LEGACY_GUEST_WRITES'] = '0'
    from app import main, studio, cloud_auth

    credentials = {'username': 'fixture-owner', 'email':'owner@example.test', 'password': 'test-only-long-password'}
    visitor = {'username': 'fixture-visitor', 'password': 'test-only-visitor-password'}
    with TestClient(main.app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000)) as client:
        remote = {'x-forwarded-host': '192.168.1.99:3000', 'x-forwarded-for': '192.168.1.10'}
        assert client.get('/api/auth/me', headers=remote).json()['can_setup'] is False
        assert client.post('/api/auth/register', json=credentials, headers=remote).status_code == 403
        assert client.get('/api/auth/me').json()['can_setup'] is True
        invalid = 'sensitive'
        reply = client.post('/api/auth/register', json={**credentials, 'password': [invalid]})
        assert reply.status_code == 422 and invalid not in reply.text
        owner = client.post('/api/auth/register', json=credentials).json()['user']['id']
        admin_cookies = dict(client.cookies)
        assert 'secure' in client.post('/api/auth/login', json=credentials, headers={'x-forwarded-proto':'https'}).headers['set-cookie'].lower()
        client.cookies.clear(); client.cookies.update(admin_cookies)
        assert client.get('/api/ai/settings', headers=remote).json()['local_allowed'] is False
        assert client.get('/api/ai/settings', headers={'x-forwarded-for':'192.168.1.10'}).json()['local_allowed'] is False
        assert client.get('/api/ai/settings').json()['local_allowed'] is True
        with patch.object(cloud_auth, 'start') as start:
            assert client.post('/api/chatgpt/connect', json={}, headers=remote).status_code == 403
            start.assert_not_called()
        assert client.get('/api/questions?q=test&semantic=true', headers=remote).status_code == 403
        assert client.post('/api/auth/register', json=visitor).status_code == 403
        account = client.post('/api/admin/accounts', json=visitor)
        assert account.status_code == 201 and 'password' not in account.text
        friend = account.json()['id']
        assert client.put(f'/api/admin/accounts/{friend}/ai-permissions', json={'local_allowed':True,'cloud_allowed':True}).status_code == 200
        with main.connect() as conn:
            for visibility in ('private','public'):
                conn.execute('INSERT INTO papers(id,paper_key,qualification,subject_code,year,season,paper_number,pair_status,created_at,updated_at,owner_id,visibility) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (visibility,visibility,'IGCSE','0580',2026,'May/June','11','qp_only','now','now',owner,visibility))
            conn.executemany("INSERT INTO questions(id,paper_id,label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,topic_auto,difficulty,updated_at) VALUES(?,'public',?,'1',1,'fixture','[]','[]','[]','','','[]','easy','now')", [(f'q-{i}',str(i)) for i in range(250)])
        assert client.get('/api/backup').content.startswith(b'SQLite format 3')
        assert not list(Path(temp).glob('.backup-*'))
        client.cookies.clear()
        assert client.post('/api/auth/login', json=visitor).status_code == 200
        friend_cookies = dict(client.cookies)
        assert client.get('/api/ai/models').status_code == 403
        assert client.get('/api/chatgpt/status').status_code == 403
        assert client.post('/api/practice', json={'question_ids':['q-1']}).status_code == 403
        assert client.post('/api/import/upload?filename=fixture.pdf', content=b'%PDF-1.4').status_code == 403
        assert not (Path(temp)/'uploads').exists()
        with main.connect() as conn: assert conn.execute('SELECT COUNT(*) FROM practice_sessions').fetchone()[0] == 0
        page = client.get('/api/questions?limit=7').json()
        assert page['total'] == 250 and len(page['questions']) == 7
        with patch.dict(studio.INDEX_STATE, errors=[{'paper_id':'private','message':'private filename'},{'paper_id':'public','message':'shared issue'}]):
            assert client.get('/api/catalog/status').json()['errors'] == [{'paper_id':'public','message':'shared issue'}]
        client.cookies.clear(); client.cookies.update(admin_cookies)
        assert client.delete(f'/api/admin/accounts/{owner}').status_code == 403
        assert client.delete(f'/api/admin/accounts/{friend}').status_code == 200
        client.cookies.clear(); client.cookies.update(friend_cookies)
        assert client.get('/api/papers').status_code == 401
    print('PASS: remote bootstrap denial, Secure cookies, validation redaction, host AI isolation, read-only visitors, scoped errors, bounded question results, transient backup, account removal')
