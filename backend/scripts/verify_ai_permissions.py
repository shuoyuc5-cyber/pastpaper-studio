"""AI permissions and shared-library checks; no external AI requests."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='studio-permissions-') as temp:
    os.environ['PASTPAPER_DATA_DIR']=temp+'/data'
    from app import main,studio,cloud_auth
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        owner=client.post('/api/auth/register',json={'username':'owner','password':'temporary-test-password'}).json()['user']['id']
        owner_cookies=dict(client.cookies)
        assert client.get('/api/ai/settings').json()['local_allowed'] is True
        with main.connect() as conn:
            conn.execute("INSERT INTO papers(id,paper_key,qualification,subject_code,year,season,paper_number,pair_status,created_at,updated_at,owner_id,visibility) VALUES('public','fixture','IGCSE','0580',2026,'May/June','11','qp_only','now','now',?,'public')",(owner,))
            conn.execute("INSERT INTO questions(id,paper_id,label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,marks,topic_auto,difficulty,updated_at) VALUES('question','public','1','1',1,'fixture','[]','[]','[]','','',1,'[]','easy','now')")
        code=client.post('/api/admin/invitations',json={}).json()['code']
        student=client.post('/api/auth/register',json={'username':'friend','password':'temporary-test-password','invite_code':code}).json()['user']['id']
        student_cookies=dict(client.cookies)
        cfg=client.get('/api/ai/settings').json()
        assert cfg['local_allowed'] is False and cfg['cloud_allowed'] is False and cfg['local_enabled'] is False
        assert client.get('/api/questions').json()['total']==1
        assert client.post('/api/practice',json={'question_ids':['question']}).status_code==200
        assert client.get('/api/admin/accounts').status_code==403
        endpoint=f'/api/admin/accounts/{student}/ai-permissions'
        assert client.put(endpoint,json={'local_allowed':True,'cloud_allowed':True}).status_code==403
        assert client.put('/api/ai/settings',json={'local_enabled':True}).status_code==403
        assert client.get('/api/ai/models').status_code==403
        assert client.get('/api/questions?semantic=true&q=test').status_code==403
        for provider in ('local','cloud'):
            assert client.post('/api/ai/tasks',json={'question_id':'question','provider':provider,'cloud_consent':True}).status_code==403
        assert client.post('/api/chatgpt/connect',json={}).status_code==403
        assert client.get('/api/chatgpt/models').status_code==403
        assert client.put('/api/chatgpt/settings',json={'enabled':True}).status_code==403
        client.cookies.clear();client.cookies.update(owner_cookies)
        assert client.put(endpoint,json={'local_allowed':True,'cloud_allowed':True}).status_code==200
        assert client.put(f'/api/admin/accounts/{owner}/ai-permissions',json={}).status_code==400
        client.cookies.clear();client.cookies.update(student_cookies)
        assert client.get('/api/ai/settings').json()['local_allowed'] is True
        assert client.put('/api/ai/settings',json={'local_enabled':True}).status_code==200
        with patch.object(cloud_auth,'start',return_value={'id':'test','url':'https://auth.openai.com/'}) as start:
            assert client.post('/api/chatgpt/connect',json={}).status_code==200
            assert start.call_args.args[0]==student
        for provider in ('local','cloud'):
            studio.AI_TASKS[provider]={'user_id':student,'provider':provider,'status':'running','cancelled':False}
        client.cookies.clear();client.cookies.update(owner_cookies)
        assert client.put(endpoint,json={'local_allowed':False,'cloud_allowed':False}).status_code==200
        assert all(studio.AI_TASKS[p]['status']=='stopped' for p in ('local','cloud'))
        client.cookies.clear();client.cookies.update(student_cookies)
        assert client.get('/api/ai/settings').json()['local_enabled'] is False
        assert client.get('/api/questions').status_code==200
    print('PASS: new-account defaults, shared questions/practice, admin-only changes, AI endpoint denial, per-account ChatGPT, grant/revoke and task cancellation')
