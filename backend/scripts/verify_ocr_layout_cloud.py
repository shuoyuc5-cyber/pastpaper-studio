"""Isolated acceptance: real offline OCR, layout revisions and mocked official OAuth.
No real account credentials or cloud inference are used.
"""
import base64, hashlib, json, os, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
import pymupdf
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
with tempfile.TemporaryDirectory(prefix='studio-ocr-') as temp:
    os.environ['PASTPAPER_DATA_DIR']=temp+'/data'
    from app import main,studio,ocr,cloud_auth
    from app.question_engine import extract_questions
    pdfs=Path(temp)/'pdfs';pdfs.mkdir();path=pdfs/'0580_s25_qp_11.pdf'
    original=pymupdf.open();p=original.new_page(width=595,height=842)
    p.insert_text((42,100),'1 Calculate 2 + 3.',fontsize=12)
    p.insert_text((72,145),'Write your answer. [1]',fontsize=12)
    p.insert_text((42,260),'2 Find the value of 8 - 4.',fontsize=12)
    p.insert_text((72,310),'Give your answer. [1]',fontsize=12)
    scan=pymupdf.open();page=scan.new_page(width=595,height=842);page.insert_image(page.rect,stream=p.get_pixmap(matrix=pymupdf.Matrix(3,3)).tobytes('png'));scan.save(path);scan.close();original.close()
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    extracted=extract_questions(str(path));assert len(extracted)==2,extracted
    assert 'Calculate' in extracted[0]['stem'] and extracted[0]['review_status']=='pending'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    assert list((Path(temp)/'data'/'ocr').glob('*.json'))
    with TestClient(main.app) as client:
        client.post('/api/auth/register',json={'username':'OCR验收','password':'temporary-password-only'}).raise_for_status()
        client.put('/api/settings/source-folder',json={'path':str(pdfs)}).raise_for_status()
        while main.SCAN_STATE['scanning']:time.sleep(.05)
        while studio.INDEX_STATE['running']:time.sleep(.05)
        studio.index_catalog()
        rows=client.get('/api/questions').json()['questions'];assert len(rows)==2,rows
        q=rows[0];sid=client.post('/api/practice',json={'question_ids':[q['id']]}).json()['id']
        r=q['segments'][0];x0,y0,x1,y1=r['rect'];middle=(y0+y1)/2
        parts=[{'label':'1-1','segments':[{'page':r['page'],'rect':[x0,y0,x1,middle]}],'context_segments':[],'marks':None},{'label':'1-2','segments':[{'page':r['page'],'rect':[x0,middle,x1,y1]}],'context_segments':[],'marks':None}]
        bad=json.loads(json.dumps(parts));bad[1]['segments'][0]['rect'][1]=middle-10
        assert client.post('/api/questions/'+q['id']+'/split',json={'parts':bad}).status_code==400
        res=client.post('/api/questions/'+q['id']+'/split',json={'parts':parts});assert res.status_code==200,res.text
        split=res.json();new=split['questions'];assert len(new)==2 and all(x['review_status']=='pending' for x in new)
        assert client.get('/api/questions/'+q['id']).json()['active']==0
        assert client.get('/api/practice/'+sid).status_code==200
        assert client.get('/api/questions/'+q['id']+'/image').status_code==200
        assert client.post('/api/practice/'+sid+'/submit').status_code==200
        studio.index_catalog();assert client.get('/api/questions').json()['total']==3
        res=client.post('/api/layout/merge',json={'question_ids':[n['id'] for n in new],'label':'1-merged'});assert res.status_code==200,res.text
        merged=res.json();assert len(merged['questions'])==1
        assert client.post('/api/layout/revisions/'+split['revision_id']+'/undo').status_code==409
        assert client.post('/api/layout/revisions/'+merged['revision_id']+'/undo').status_code==200
        assert client.post('/api/layout/revisions/'+split['revision_id']+'/undo').status_code==200
        assert client.get('/api/questions/'+q['id']).status_code==200
        assert client.get('/api/chatgpt/status').json()['enabled'] is False
        assert client.put('/api/chatgpt/settings',json={'enabled':True,'model':'fake'}).status_code==400
        flow=client.post('/api/chatgpt/connect',json={}).json();params=parse_qs(urlparse(flow['url']).query)
        assert params['client_id']==['dynamic_agent_client'] and params['code_challenge_method']==['S256']
        assert params['redirect_uri'][0].startswith('http://127.0.0.1:')
        assert 'resource.invoke' in params['scope'][0] and 'chatgpt.tokens.use.direct' in params['scope'][0]
        state=cloud_auth.FLOWS[flow['id']]
        try:cloud_auth.finish(state,{'state':['wrong']});raise AssertionError('state accepted')
        except ValueError:pass
        assert client.post('/api/chatgpt/flows/'+flow['id']+'/cancel',json={}).status_code==200
        assert client.get('/api/chatgpt/flows/'+flow['id']).json()['status']=='cancelled'
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));public['kid']='test-key'
        nonce='test-nonce';client_id='oaiapp_test';claims={'iss':cloud_auth.ISSUER,'aud':client_id,'sub':'subject-a','nonce':nonce,'iat':int(time.time()),'exp':int(time.time())+120,'email':'test@example.invalid'}
        encoded=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test-key'})
        class JWKS:
            def raise_for_status(self):pass
            def json(self):return {'keys':[public]}
        with patch.object(cloud_auth,'metadata',return_value={'issuer':cloud_auth.ISSUER,'jwks_uri':cloud_auth.ISSUER+'/jwks'}),patch.object(cloud_auth.httpx.Client,'get',return_value=JWKS()):
            assert cloud_auth.validate_identity({'id_token':encoded},client_id,nonce)['sub']=='subject-a'
            for wrong in ['bad-nonce']:
                try:cloud_auth.validate_identity({'id_token':encoded},client_id,wrong);raise AssertionError('nonce accepted')
                except ValueError:pass
            try:cloud_auth.validate_identity({'id_token':encoded},'wrong-client',nonce);raise AssertionError('audience accepted')
            except jwt.InvalidAudienceError:pass
        user_id=client.get('/api/auth/me').json()['user']['id']
        tokens={'id_token':encoded,'access_token':'mock-access','refresh_token':'mock-refresh','token_type':'Bearer','expires_in':3600,'scope':'openid profile email resource.invoke chatgpt.tokens.use.direct'}
        class TokenResponse:
            status_code=200
            def json(self):return tokens
        successful={'id':'mock-flow','state':'mock-state','nonce':nonce,'verifier':'test-pkce','redirect_uri':'http://127.0.0.1:1234/auth/callback','user_id':user_id,'client_id':None,'previous':None,'profile_id':None,'status':'pending','expires':time.time()+300}
        with patch.object(cloud_auth,'metadata',return_value={'issuer':cloud_auth.ISSUER,'jwks_uri':cloud_auth.ISSUER+'/jwks'}),patch.object(cloud_auth.httpx.Client,'get',return_value=JWKS()),patch.object(cloud_auth.httpx.Client,'post',return_value=TokenResponse()):
            cloud_auth.finish(successful,{'state':['mock-state'],'code':['mock-code'],'client_id':[client_id]})
        assert successful['status']=='completed' and cloud_auth.view(user_id)['sharing']
        assert cloud_auth.view(user_id)['enabled'] is False
        pid=cloud_auth.view(user_id)['active']
        assert cloud_auth.load(user_id)['profiles'][pid]['client_id']==client_id
        cloud_auth.save(user_id,{'profiles':{},'active':None,'enabled':False,'model':''})
        assert (cloud_auth.folder()/(user_id+'.json')).stat().st_mode & 0o777==0o600
        assert client.post('/api/ai/tasks',json={'question_id':q['id'],'provider':'cloud','cloud_consent':True}).status_code==400
        assert client.get('/api/ocr/status').json()['files']
        fallback=pymupdf.open();p=fallback.new_page();p.insert_text((72,100),'Scanned or unfamiliar layout for manual review');fallback.save(pdfs/'0580_s24_qp_11.pdf');fallback.close()
        main.scan_library();studio.index_catalog()
        paper=next(p for p in client.get('/api/papers').json()['papers'] if p['year']==2024)
        manual=client.post('/api/papers/'+paper['id']+'/layout-seed',json={});assert manual.status_code==200,manual.text
        assert manual.json()['label']=='1-manual' and manual.json()['marks'] is None
        assert client.post('/api/papers/'+paper['id']+'/layout-seed',json={}).status_code==409
        code=client.post('/api/admin/invitations',json={}).json()['code']
        client.post('/api/auth/register',json={'username':'隔离学生','password':'temporary-password-only','invite_code':code}).raise_for_status()
        assert client.get('/api/chatgpt/status').json()['connected'] is False
        assert client.get('/api/questions/'+q['id']).status_code==404
        assert client.post('/api/papers/'+paper['id']+'/layout-seed',json={}).status_code==404
    print('PASS: image-only PDF OCR + unchanged source; split/merge/undo; original attempt preserved; PKCE/cancel/state; signed JWT/nonce/audience; 0600 credentials; cloud off; no live inference')
