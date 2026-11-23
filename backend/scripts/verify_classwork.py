"""Assignment lifecycle, versioning, permissions and deterministic grading."""
import os
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import time
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pymupdf

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='studio-classwork-') as directory:
    os.environ['PASTPAPER_DATA_DIR']=directory
    os.environ['PASTPAPER_LEGACY_GUEST_WRITES']='0'
    from app import main

    def password(name):return {'username':name,'password':'test-only-classwork-'+name}
    prefix='/api/classroom'
    with TestClient(main.app) as client:
        admin=client.post('/api/auth/register',json=password('owner')).json()['user']
        ids={}
        for name in ('teacher-a','teacher-b','student-a','student-b','student-c'):
            account=client.post('/api/admin/accounts',json=password(name))
            assert account.status_code==201,account.text
            ids[name]=account.json()['id']
            if name.startswith('teacher'):
                assert client.put('/api/admin/accounts/'+ids[name]+'/role',json={'role':'teacher'}).status_code==200

        def login(name):
            client.cookies.clear()
            response=client.post('/api/auth/login',json=password(name))
            assert response.status_code==200,response.text

        login('teacher-a')
        room=client.post(prefix+'/classes',json={'name':'Class A','subject':'Math','admission':'automatic'}).json()
        class_url=prefix+'/classes/'+room['id']
        with main.connect() as conn:
            for i,owner,visibility in [(1,admin['id'],'public'),(2,ids['teacher-b'],'private')]:
                pid=f'paper-{i}'
                conn.execute('INSERT INTO papers(id,paper_key,qualification,subject_code,year,season,paper_number,pair_status,created_at,updated_at,owner_id,visibility) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                             (pid,pid,'IGCSE','0580',2026,'May/June','11','qp_only','now','now',owner,visibility))
                conn.execute("INSERT INTO questions(id,paper_id,label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,marks,topic_auto,difficulty,review_status,updated_at) VALUES(?,?,'1','1',1,?,'[]','[]','[]','','',2,'[\"Number\"]','easy','confirmed','now')",
                             ('q-'+pid,pid,'Authorized arithmetic' if i==1 else 'Another teacher private'))
        generated=client.post(class_url+'/generate',json={'count':1,'total_marks':2,'topic':'Number'})
        assert generated.status_code==200 and generated.json()['questions'][0]['text']=='Authorized arithmetic'
        assert client.post(class_url+'/generate',json={'count':2}).status_code==400
        with pymupdf.open() as document:
            page=document.new_page()
            page.insert_text((60,90),'1. First classroom question\nA. First option\nB. Second option\n\n2. Explain your reasoning [3]')
            pdf=document.tobytes()
            raster=page.get_pixmap(matrix=pymupdf.Matrix(2.5,2.5))
            png=raster.tobytes('png')
            jpeg=raster.tobytes('jpeg')
        imported=client.post(class_url+'/document-import',content=pdf,headers={'Content-Type':'application/pdf'})
        assert imported.status_code==200,imported.text
        assert imported.json()['questions'][0]['options']==['First option','Second option']
        assert imported.json()['questions'][1]['marks']==3
        docx=BytesIO()
        with ZipFile(docx,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>1. Explain this result [2]</w:t></w:r></w:p></w:body></w:document>')
        docx_headers={'Content-Type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
        imported=client.post(class_url+'/document-import',content=docx.getvalue(),headers=docx_headers)
        assert imported.status_code==200 and imported.json()['questions'][0]['marks']==2
        assert client.post(class_url+'/document-import',content=b'fake',headers={'Content-Type':'application/pdf'}).status_code==422
        for content, kind in ((png,'png'),(jpeg,'jpeg')):
            image=client.post(class_url+'/document-import',content=content,headers={'Content-Type':'image/'+kind})
            assert image.status_code==200 and 'First classroom question' in str(image.json()), image.text
        draft={'title':'Real class assessment','rules':{'deadline':int(time.time())+60,'leaderboard':True,'reveal_answers':True,'shuffle_questions':True,'shuffle_options':True},
               'questions':[
                   {'text':'Pick 2','kind':'single','marks':1,'options':['2','3'],'accepted':['0']},
                   {'text':'Pick two even numbers','kind':'multiple','marks':4,'options':['2','4','5'],'accepted':['0','1'],'partial_credit':True},
                   {'text':'Seven is odd','kind':'boolean','marks':1,'accepted':['true']},
                   {'text':'Name the institution','kind':'fill','marks':2,'accepted':['Oxford University','University of Oxford'],'ignore_punctuation':True},
                   {'text':'Approximate root','kind':'number','marks':2,'accepted':['1.414'],'tolerance':0.01},
                   {'text':'Explain the method','kind':'short','marks':3},
               ]}
        response=client.post(class_url+'/assignments',json=draft)
        assert response.status_code==201,response.text
        assignment=response.json()
        url=prefix+'/assignments/'+assignment['id']
        assert client.get(url+'?manage=true').json()['questions'][0]['accepted']==['0']
        assert client.get(url).status_code==404
        published=client.post(url+'/publish')
        assert published.status_code==200,published.text
        code=published.json()['code']
        assert code.startswith('A-')
        assert client.put(url,json=draft).status_code==409

        login('teacher-b')
        assert client.get(url+'?manage=true').status_code==404
        assert client.get(url+'/submissions').status_code==404
        assert client.post(class_url+'/generate',json={'count':1}).status_code==404
        assert client.post(class_url+'/document-import',content=pdf,headers={'Content-Type':'application/pdf'}).status_code==404
        assert client.post(url+'/publish').status_code==404

        for name in ('student-a','student-c'):
            login(name)
            assert client.post(prefix+'/join',json={'code':room['join_code']}).json()['status']=='active'
        login('student-b')
        assert client.post(prefix+'/assignment-code',json={'code':code}).status_code==404
        assert client.get(url).status_code==404
        assert client.post(url+'/attempts').status_code==404

        login('student-a')
        assert client.post(prefix+'/assignment-code',json={'code':code}).json()['id']==assignment['id']
        response=client.post(url+'/attempts')
        assert response.status_code==200,response.text
        attempt=response.json()
        assert all('accepted' not in q for q in attempt['questions'])
        assert 'grades' not in attempt
        assert client.post(url+'/attempts').json()['id']==attempt['id']
        attempt_url=url+'/attempts/'+attempt['id']
        answers={0:'0',1:['0'],2:'false',3:'  UNIVERSITY  OF OXFORD! ',4:'1.42',5:'The method is to simplify.'}
        saved=client.put(attempt_url,json={'revision':0,'answers':answers})
        assert saved.status_code==200 and saved.json()['revision']==1
        assert client.put(attempt_url,json={'revision':0,'answers':{}}).status_code==409
        assert client.get(url).json()['attempts'][0]['answers']['0']=='0'

        login('student-c')
        assert client.put(attempt_url,json={'revision':1,'answers':{}}).status_code==404
        assert client.get(url+'/submissions').status_code==403
        login('student-a')
        submitted=client.post(attempt_url+'/submit',json={'revision':1,'answers':answers})
        assert submitted.status_code==200,submitted.text
        result=submitted.json()
        assert [result['grades'][str(i)]['marks'] for i in range(6)]==[1,2,0,2,2,None]
        assert result['metrics']=={'marks':7,'available_marks':10,'total_marks':13,'graded':5,'pending':1,'accuracy':60.0,'percentage':70.0}
        assert client.post(attempt_url+'/submit',json={'revision':1,'answers':{}}).json()['grades']==result['grades']
        assert client.post(url+'/attempts').status_code==409
        assert client.get(url+'/leaderboard').json()['ranking']==[]

        login('teacher-a')
        review=client.get(url+'/submissions').json()['submissions'][0]
        assert review['username']=='student-a' and review['answers']['5']==answers[5]
        grade_url=url+'/submissions/'+attempt['id']+'/grades/5'
        assert client.put(grade_url,json={'marks':4}).status_code==400
        graded=client.put(grade_url,json={'marks':2,'feedback':'Show one more step.'})
        assert graded.json()['marks']==9 and graded.json()['pending']==0
        assert client.put(grade_url,json={'marks':3}).status_code==200
        performance=client.get(class_url+'/analytics?period=7').json()
        assert performance['students']==2 and performance['published']==1
        assert performance['assignments'][0]['completed']==1 and performance['assignments'][0]['completion']==50
        with main.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM class_grade_audit').fetchone()[0]==2
        # A manager can have a historical student attempt; that is not permission to grade it.
        login('owner')
        with main.connect() as conn:
            conn.execute('UPDATE class_attempts SET student_id=? WHERE id=?',(admin['id'],attempt['id']))
        assert client.put(grade_url,json={'marks':0}).status_code==403
        with main.connect() as conn:
            conn.execute('UPDATE class_attempts SET student_id=? WHERE id=?',(ids['student-a'],attempt['id']))
        login('teacher-a')
        revised=client.post(class_url+'/assignments',json={**draft,'previous_id':assignment['id'],'title':'Revised version'})
        assert revised.json()['version']==2
        assert client.post(class_url+'/assignments',json={**draft,'previous_id':assignment['id']}).status_code==409
        with main.connect() as conn:
            conn.execute('UPDATE class_assignments SET rules=json_set(rules,\'$.deadline\',?) WHERE id=?',(int(time.time())-2,assignment['id']))
        login('student-c')
        assert client.post(url+'/attempts').status_code==409
        assert client.get(url).json()['attempts']==[]
        assert client.get(class_url+'/analytics').status_code==403
        ranking=client.get(url+'/leaderboard').json()['ranking']
        assert ranking[0]['rank']==1 and ranking[0]['marks']==10 and 'student-a' not in str(ranking)

        login('owner')
        assert client.put('/api/admin/accounts/'+ids['student-a']+'/role',json={'role':'teacher'}).status_code==200
        assert client.delete(class_url+'/members/'+ids['student-a']).status_code==200
        assert client.put('/api/admin/accounts/'+ids['teacher-a']+'/role',json={'role':'student','replacement_id':ids['student-a']}).status_code==409
        assert client.put('/api/admin/accounts/'+ids['teacher-a']+'/role',json={'role':'student','replacement_id':ids['teacher-b']}).status_code==200
        login('teacher-a')
        assert client.put(grade_url,json={'marks':2}).status_code==403
        assert client.get(url+'/submissions').status_code==403
        login('teacher-b')
        assert client.get(url+'/submissions').json()['submissions'][0]['metrics']['marks']==10
    print('PASS: scoped bank, draft, published versions and codes, draft conflicts, grading and overrides, private attempts, deadline and leaderboard')
