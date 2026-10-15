"""Draft selection checks with synthetic PDFs and an isolated database."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='studio-builder-') as temp:
    os.environ['PASTPAPER_DATA_DIR'] = temp + '/data'
    from app import main, studio
    from fastapi.testclient import TestClient
    import pymupdf

    pdf = Path(temp) / 'synthetic.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 80), 'Synthetic question fixture')
        doc.save(pdf)
    with TestClient(main.app) as client:
        owner = client.post('/api/auth/register', json={'username':'builder-owner','password':'temporary-test-password'}).json()['user']['id']
        with main.connect() as conn:
            conn.execute("INSERT INTO source_files(id,path,filename,status,added_at,updated_at,owner_id) VALUES('source',?,'synthetic.pdf','completed','now','now',?)", (str(pdf), owner))
            conn.execute("INSERT INTO papers(id,paper_key,qualification,subject_code,year,season,paper_number,qp_file_id,pair_status,created_at,updated_at,owner_id) VALUES('paper','fixture','IGCSE','0580',2026,'May/June','11','source','qp_only','now','now',?)", (owner,))
            for root in range(1,7):
                for part in ('a','b'):
                    label = f'{root}({part})'
                    conn.execute("""INSERT INTO questions(id,paper_id,label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,marks,topic_auto,difficulty,updated_at)
                      VALUES(?,'paper',?,?,1,'Synthetic fixture',?,'[]','[]','','',2,'["Probability"]','easy','now')""", (label,label,str(root),studio.js([{'page':1,'rect':[40,50,300,100]}])))
        assert client.post('/api/builder/auto', json={'count':5}).status_code == 400
        draft = client.post('/api/builder/auto', json={'count':5,'include_pending':True,'total_marks':10})
        assert draft.status_code == 200, draft.text
        draft = draft.json()
        assert len(draft['items']) == 5 and draft['pending_count'] == 5
        assert len({i['question_id'].split('(')[0] for i in draft['items']}) == 5
        for kind in ('qp','ms','study'):
            assert client.post('/api/builder/export?kind='+kind, json={'items':draft['items']}).status_code == 400
        assert all(q['review_status']=='pending' for q in client.get('/api/questions').json()['questions'])
        assert client.post('/api/builder/auto', json={'count':1,'include_pending':True,'subject_code':'9709'}).status_code == 400
        assert client.post('/api/builder/auto', json={'count':5,'include_pending':True,'total_marks':11}).status_code == 400
        # This confirmation applies only to a disposable synthetic fixture.
        with main.connect() as conn:
            conn.execute("UPDATE questions SET review_status='confirmed' WHERE id='1(a)'")
        confirmed = client.post('/api/builder/auto', json={'count':1}).json()
        assert confirmed['pending_count'] == 0 and confirmed['items'][0]['question_id'] == '1(a)'
        mixed = client.post('/api/builder/auto', json={'count':5,'include_pending':True}).json()
        assert mixed['pending_count'] == 4 and mixed['items'][0]['question_id'] == '1(a)'
        assert client.post('/api/builder/export?kind=qp', json={'items':confirmed['items']}).status_code == 200
        assert client.post('/api/builder/export?kind=ms', json={'items':confirmed['items']}).status_code == 400
        owner_cookies=dict(client.cookies)
        code=client.post('/api/admin/invitations',json={}).json()['code']
        student=client.post('/api/auth/register', json={'username':'builder-student','password':'temporary-test-password','invite_code':code}).json()['user']['id']
        assert client.post('/api/builder/auto', json={'count':1,'include_pending':True}).status_code == 400
        assert client.get('/api/questions/1(a)/image').status_code==404
        client.cookies.clear();client.cookies.update(owner_cookies)
        image=client.get('/api/questions/1(a)/image')
        assert image.status_code==200 and image.content.startswith(b'\x89PNG')
        digest=main.sha256_file(pdf)
        moved=pdf.with_name('moved.pdf');pdf.rename(moved)
        missing=client.get('/api/questions/1(a)/image')
        assert missing.status_code==404 and 'synthetic.pdf' in missing.json()['detail']
        with main.connect() as conn:
            conn.execute("UPDATE source_files SET file_hash=? WHERE id='source'",(digest,))
            conn.execute("INSERT INTO source_files(id,path,filename,status,file_hash,added_at,updated_at,owner_id) VALUES('copy',?,'copy.pdf','duplicate',?,'now','now',?)",(str(moved),digest,student))
        assert client.get('/api/questions/1(a)/image').status_code==404
        with main.connect() as conn:conn.execute("UPDATE source_files SET owner_id=? WHERE id='copy'",(owner,))
        assert client.get('/api/questions/1(a)/image').status_code==200
        assert client.get('/api/files/source').status_code==200
        assert client.get('/api/files/source/pages/1').status_code==200
        with moved.open('ab') as f:f.write(b'changed')
        assert client.get('/api/questions/1(a)/image').status_code==404
    print('PASS: draft selection, export gates, image rendering, missing-file messages, exact-copy recovery, account isolation')
