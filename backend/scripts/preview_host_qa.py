"""Loopback host preview with one synthetic question and no existing accounts or data."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pymupdf
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with TemporaryDirectory(prefix='pastpaper-host-browser-qa-') as temporary:
    os.environ['PASTPAPER_DATA_DIR'] = temporary
    from app import main, studio

    main.init_db()
    paper_path = Path(temporary) / '0580_s26_qp_11.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((60, 85), '1. Find the probability of getting a six. Synthetic QA question.')
        if os.environ.get('HOST_QA_BUILDER') == '1':
            for i in range(2,7):
                pdf.new_page().insert_text((60, 85), f'{i}. Explain refraction in a glass block. Synthetic QA question.')
        pdf.save(paper_path)
    with main.connect() as conn:
        owner = studio.insert_account(conn, studio.AccountCredentials(username='fixture-admin', email='admin@example.test', password='qa-only-password'), 'admin')['id']
        for username in ('fixture-teacher', 'fixture-student'):
            studio.insert_account(conn, studio.AccountCredentials(username=username, email=username+'@example.test', password='qa-only-password'), 'student')
        conn.execute("INSERT INTO source_files (id,path,filename,file_hash,size_bytes,mtime_ns,status,file_type,pages,added_at,updated_at,owner_id) VALUES ('fixture-source',?,?,?,?,?,'completed','qp',1,?,?,?)", (str(paper_path),paper_path.name,main.sha256_file(paper_path),paper_path.stat().st_size,paper_path.stat().st_mtime_ns,main.now_iso(),main.now_iso(),owner))
        conn.execute("INSERT INTO papers (id,paper_key,qualification,subject,subject_code,year,season,paper_number,qp_file_id,pair_status,created_at,updated_at,owner_id) VALUES ('fixture-paper','fixture-key','Cambridge IGCSE','Mathematics','0580',2026,'May/June','11','fixture-source','qp_only',?,?,?)", (main.now_iso(),main.now_iso(),owner))
        region = json.dumps([{'page':1,'rect':[40,45,510,140]}])
        conn.execute("INSERT INTO questions (id,paper_id,label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,marks,topic_auto,difficulty,review_status,updated_at) VALUES ('fixture-question','fixture-paper','1','1',1,'Find the probability of getting a six. Synthetic QA question.',?,'[]','[]','','',1,'[]','easy','confirmed',?)", (region, main.now_iso()))
        if os.environ.get('HOST_QA_BUILDER') == '1':
            conn.executemany("""INSERT INTO questions (id,paper_id,label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,marks,topic_auto,difficulty,review_status,updated_at)
                VALUES (?,'fixture-paper',?,?,1,'Synthetic refraction exercise',?,'[]','[]','','',2,'[]','easy','pending',?)""",
                [(f'fixture-refraction-{i}', str(i), str(i), studio.js([{'page':i,'rect':[40,45,510,140]}]), main.now_iso()) for i in range(2,7)])
    uvicorn.run(main.app, host='127.0.0.1', port=int(os.environ.get('HOST_QA_PORT', '39222')), proxy_headers=False, access_log=False)
