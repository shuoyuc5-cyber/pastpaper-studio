"""Acceptance checks use a temporary database and the two user-provided originals."""
import os, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
with tempfile.TemporaryDirectory(prefix='studio-acceptance-') as temp:
    os.environ['PASTPAPER_DATA_DIR']=temp+'/data'
    from app import main, studio
    from fastapi.testclient import TestClient
    import pymupdf
    folder=Path(temp)/'pdf';folder.mkdir()
    source=Path(os.environ.get('PASTPAPER_SAMPLE_DIR',ROOT/'samples'))
    for kind,sub in [('qp','试题_Question_Papers'),('ms','答案_Mark_Schemes')]:
        sample=source/f'0580_s26_{kind}_11.pdf'
        if not sample.is_file():raise SystemExit(f'Supply your own sample PDF using PASTPAPER_SAMPLE_DIR: {sample}')
        (folder/sample.name).symlink_to(sample.resolve())
    with TestClient(main.app) as client:
        assert client.get('/api/papers').status_code==401
        assert client.post('/api/auth/register',json={'username':'验收管理员','password':'temporary-password-only'}).status_code==200
        assert client.put('/api/settings/source-folder',json={'path':str(folder)}).status_code==200
        import time
        while main.SCAN_STATE['scanning']:time.sleep(.05)
        studio.index_catalog()
        rows=client.get('/api/questions').json()['questions']
        assert len(rows)==47 and sum(q['marks'] for q in rows)==80,(len(rows),client.get('/api/imports').json())
        q=next(q for q in rows if q['label']=='7(a)(i)')
        assert q['context_segments'] and q['official_answer']=='1/8 oe' and q['ms_segments'][0]['page']==9
        assert client.post('/api/builder/auto',json={'count':5}).status_code==400
        draft=client.post('/api/builder/auto',json={'count':5,'include_pending':True})
        assert draft.status_code==200,draft.text
        draft=draft.json()
        assert len(draft['items'])==5 and draft['pending_count']==5
        ids={i['question_id'] for i in draft['items']}
        assert len({(r['paper_id'],r['root_label']) for r in rows if r['id'] in ids})==5
        assert client.post('/api/builder/export',json={'items':draft['items']}).status_code==400
        assert all(r['review_status']=='pending' for r in client.get('/api/questions').json()['questions'])
        edit={k:q[k] for k in ['label','stem','tags','difficulty','segments','context_segments','ms_segments']};edit['review_status']='confirmed'
        assert client.put('/api/questions/'+q['id'],json=edit).status_code==200
        for answer in ['1/8','0.125','12.5%','2/16','0.5']:
            sid=client.post('/api/practice',json={'question_ids':[q['id']]}).json()['id']
            assert client.put('/api/practice/'+sid+'/draft',json={'answers':{q['id']:{'answer':answer}}}).status_code==200
            result=client.post('/api/practice/'+sid+'/submit').json()['results'][0]
            assert result['score']==(0 if answer=='0.5' else 1),result
            assert client.post('/api/practice/'+sid+'/submit').status_code==409
        assert client.get('/api/questions?mistakes=true').json()['total']==1
        assert client.put('/api/questions/'+q['id']+'/bookmark',json={'saved':True,'note':'复习概率'}).status_code==200
        assert client.get('/api/questions?saved=true').json()['total']==1
        for kind in ['qp','ms','study']:
            response=client.post('/api/builder/export?kind='+kind,json={'title':'概率练习','items':[{'question_id':q['id']}]})
            assert response.status_code==200,response.text[:200]
            with pymupdf.open(stream=response.content,filetype='pdf') as doc:assert len(doc)>0
        assert studio.polynomial('b+5')==studio.polynomial('5+b')
        assert studio.polynomial('__import__("os")') is None
        admin_cookies=dict(client.cookies)
        code=client.post('/api/admin/invitations',json={}).json()['code']
        assert client.post('/api/auth/register',json={'username':'验收学生','password':'temporary-password-only','invite_code':code}).status_code==200
        assert client.get('/api/questions').json()['total']==0
        assert client.post('/api/builder/auto',json={'count':1,'include_pending':True}).status_code==400
        assert client.get('/api/questions/'+q['id']).status_code==404
        assert client.get('/api/files/'+q.get('qp_file_id','invalid')).status_code==404
        assert client.post('/api/settings/select-folder').status_code==403
        client.cookies.clear();client.cookies.update(admin_cookies)
        p=client.get('/api/papers').json()['papers'][0]
        assert client.put('/api/papers/'+p['id']+'/sharing',json={'visibility':'public','rights_confirmed':True}).status_code==200
        assert client.get('/api/ai/settings').json()['cloud_enabled'] is False
    print('PASS: 47 leaf questions / 80 marks; Q7 context + official MS; equivalent grading; drafts; mistakes; bookmarks; 3 PDF exports; account isolation; cloud off')
