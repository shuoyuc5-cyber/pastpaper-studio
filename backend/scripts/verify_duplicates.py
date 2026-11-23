"""Exercise duplicate cleanup against disposable files and an isolated database."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='pastpaper-duplicates-') as directory:
    os.environ['PASTPAPER_DATA_DIR']=directory
    from app import main

    with TestClient(main.app) as client:
        owner=client.post('/api/auth/register',json={'username':'duplicate-admin','password':'test-only-password'}).json()['user']['id']
        root=Path(directory)
        original=root/'original.pdf'
        duplicate=root/'duplicate.pdf'
        changed=root/'changed.pdf'
        original.write_bytes(b'fixture')
        duplicate.write_bytes(b'fixture')
        changed.write_bytes(b'changed')
        digest=hashlib.sha256(b'fixture').hexdigest()
        with main.connect() as conn:
            for identifier,path,status in [('original',original,'needs_review'),('duplicate',duplicate,'duplicate'),
                                           ('changed',changed,'duplicate'),('missing',root/'missing.pdf','duplicate')]:
                conn.execute("""INSERT INTO source_files(id,path,filename,file_hash,status,owner_id,added_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""",(identifier,str(path),path.name,digest,status,owner,main.now_iso(),main.now_iso()))

        endpoint='/api/admin/duplicates'
        response=client.post(endpoint+'/clean',json={'ids':['duplicate','missing','changed']})
        assert response.status_code==200,response.text
        assert [r['error'] is None for r in response.json()['results']]==[True,True,False]
        assert original.read_bytes()==b'fixture' and changed.read_bytes()==b'changed' and not duplicate.exists()
        assert len(list((root/'duplicate_trash').glob('*.pdf')))==1
        assert client.delete(endpoint+'/duplicate').status_code==200
        assert client.get(endpoint).json()['groups']==[]

        # A restored/re-imported copy can be cleaned without a stale recycle bin key rolling the move back.
        duplicate.write_bytes(b'fixture')
        with main.connect() as conn:
            conn.execute("UPDATE source_files SET status='duplicate' WHERE id='duplicate'")
        assert client.delete(endpoint+'/duplicate').status_code==200
        assert not duplicate.exists() and len(list((root/'duplicate_trash').glob('*.pdf')))==2

        original.unlink()
        changed.write_bytes(b'fixture')
        with main.connect() as conn:
            conn.execute("UPDATE source_files SET status='duplicate' WHERE id='changed'")
        assert client.delete(endpoint+'/changed').status_code==409
        assert changed.exists()
        assert client.get(endpoint).json()['groups']==[]
        with main.connect() as conn:
            assert conn.execute("SELECT status FROM source_files WHERE id='changed'").fetchone()[0]=='needs_review'

        first=root/'a'/'0580_s26_qp_11.pdf'
        second=root/'b'/first.name
        third=root/'c'/'renamed.pdf'
        for path in (first,second,third):
            path.parent.mkdir()
        first.write_bytes(b'first')
        second.write_bytes(b'other')
        third.write_bytes(b'first')
        with main.connect() as conn:
            for identifier,path in [('first',first),('second',second),('third',third)]:
                conn.execute("""INSERT INTO source_files(id,path,filename,file_hash,status,owner_id,added_at,updated_at)
                    VALUES(?,?,?,?,'completed',?,?,?)""",
                    (identifier,str(path),path.name,main.sha256_file(first),owner,main.now_iso(),main.now_iso()))
            main.attach_to_paper(conn,'first',main.parse_filename(first.name))
            paper_id=conn.execute("SELECT id FROM papers WHERE qp_file_id='first'").fetchone()[0]
            for label in ('1','2','3'):
                conn.execute("""INSERT INTO questions(id,paper_id,label,root_label,leaf,stem,segments,context_segments,
                    ms_segments,official_answer,official_guidance,topic_auto,difficulty,updated_at)
                    VALUES(?,?,?,?,1,'fixture','[]','[]','[]','','','[]','easy',?)""",
                    (label,paper_id,label,label,main.now_iso()))

        def copies():
            return [len(group['copies']) for group in client.get(endpoint).json()['groups']]

        assert copies()==[2]
        alias=root/'hard-link.pdf'
        os.link(first,alias)
        with main.connect() as conn:
            conn.execute("""INSERT INTO source_files(id,path,filename,file_hash,status,owner_id,added_at,updated_at)
                VALUES('alias',?,?,?,'completed',?,?,?)""",
                (str(alias),alias.name,main.sha256_file(first),owner,main.now_iso(),main.now_iso()))
        assert copies()==[2]
        second.write_bytes(b'first')
        assert copies()==[3]
        third.unlink()
        assert copies()==[2]
        second.write_bytes(b'other')
        assert copies()==[]
        with main.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM questions WHERE paper_id=?",(paper_id,)).fetchone()[0]==3
            assert conn.execute("SELECT qp_file_id FROM papers WHERE id=?",(paper_id,)).fetchone()[0]=='first'
            assert conn.execute("SELECT status FROM source_files WHERE id='second'").fetchone()[0]=='needs_review'
        assert first.exists() and second.exists()
        print('PASS: verified two and three copies, same-name different bytes, external removal, linked questions, legacy flags, idempotent cleanup and last-copy protection')
