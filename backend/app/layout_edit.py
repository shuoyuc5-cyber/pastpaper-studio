"""Transactional split/merge with reversible revisions and preserved attempts."""
import json
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from .question_engine import validate_segments, segment_text
import pymupdf

class Part(BaseModel):
    label: str = Field(min_length=1,max_length=40,pattern=r'^[0-9][0-9a-zA-Z()_.-]*$')
    segments: list[dict] = Field(min_length=1,max_length=30)
    context_segments: list[dict] = Field(default_factory=list,max_length=30)
    ms_segments: list[dict] = Field(default_factory=list,max_length=30)
    marks: int | None = Field(default=None,ge=0,le=100)
class Split(BaseModel):
    parts: list[Part] = Field(min_length=2,max_length=20)
class Merge(BaseModel):
    question_ids: list[str] = Field(min_length=2,max_length=20)
    label: str = Field(min_length=1,max_length=40,pattern=r'^[0-9][0-9a-zA-Z()_.-]*$')

def install(app,S):
    def replace(u,old,parts,kind):
        if len({q['paper_id'] for q in old})!=1: raise HTTPException(400,'只能合并同一试卷的题目')
        paper=old[0]['paper'];qp=S.source_path(paper,'qp');ms=S.source_path(paper,'ms') if any(p.ms_segments for p in parts) else None
        labels=[p.label for p in parts]
        if len(set(labels))!=len(labels): raise HTTPException(400,'新题号不能重复')
        try:
            for p in parts:
                validate_segments(qp,p.segments+p.context_segments)
                if p.ms_segments: validate_segments(ms,p.ms_segments)
            if kind=='split':
                # A split must partition the original body, without dropping or duplicating material.
                original=old[0]['segments']
                for part in parts:
                    for seg in part.segments:
                        if not any(seg['page']==o['page'] and pymupdf.Rect(o['rect']).contains(pymupdf.Rect(seg['rect'])) for o in original):
                            raise ValueError('拆分范围必须位于原题范围内')
                for o in original:
                    pieces=[pymupdf.Rect(s['rect']) for p in parts for s in p.segments if s['page']==o['page']]
                    area=0
                    for i,r in enumerate(pieces):
                        area+=r.get_area()
                        if any((r & t).get_area()>.5 for t in pieces[:i]): raise ValueError('拆分区域不能重叠')
                    if abs(area-pymupdf.Rect(o['rect']).get_area())>2: raise ValueError('拆分必须完整保留原题的所有区域')
        except ValueError as exc: raise HTTPException(400,str(exc))
        created=[];stamp=S.now()
        with S.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            snapshots=[]
            for q in old:
                row=conn.execute('SELECT * FROM questions WHERE id=? AND active=1',(q['id'],)).fetchone()
                if not row or row['updated_at']!=q['updated_at']: raise HTTPException(409,'题目已被其他操作修改，请刷新')
                snapshots.append(dict(row))
            for p in parts:
                if conn.execute('SELECT 1 FROM questions WHERE paper_id=? AND label=?',(old[0]['paper_id'],p.label)).fetchone(): raise HTTPException(409,'题号 '+p.label+' 已存在，请使用新题号')
                row=dict(snapshots[0]);row.update(id=S.uid(),label=p.label,leaf=1,parent_label=old[0]['parent_label'] if kind=='split' else None,
                    marks=p.marks,segments=S.js(p.segments),context_segments=S.js(p.context_segments),ms_segments=S.js(p.ms_segments),
                    official_answer='',official_guidance='',review_status='pending',manually_edited=1,active=1,formula_review=1,updated_at=stamp)
                with pymupdf.open(qp) as doc: row['stem']=segment_text(doc,p.context_segments+p.segments)
                if p.ms_segments:
                    with pymupdf.open(ms) as doc: row['official_guidance']=segment_text(doc,p.ms_segments)
                conn.execute(f"INSERT INTO questions({','.join(row)}) VALUES({','.join('?' for _ in row)})",list(row.values()))
                created.append(row['id'])
            for q in old: conn.execute('UPDATE questions SET active=0,manually_edited=1 WHERE id=?',(q['id'],))
            rid=S.uid();conn.execute('INSERT INTO layout_revisions VALUES(?,?,?,?,?,?,?,0)',(rid,u['id'],old[0]['paper_id'],kind,S.js(snapshots),S.js(created),stamp))
        return {'revision_id':rid,'questions':[S.question_for(q,u) for q in created]}

    @app.post('/api/papers/{pid}/layout-seed')
    def seed(request:Request,pid:str):
        u=S.user(request);p=S.paper_for(pid,u,True)
        with pymupdf.open(S.source_path(p,'qp')) as doc:
            segments=[{'page':i+1,'rect':list(page.rect)} for i,page in enumerate(doc)]
            stem=segment_text(doc,segments)
        with S.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM questions WHERE paper_id=?',(pid,)).fetchone():raise HTTPException(409,'试卷已有拆题记录，请在题目检索中编辑已有题目')
            qid=S.uid();stamp=S.now()
            conn.execute("INSERT INTO questions(id,paper_id,label,parent_label,root_label,leaf,stem,segments,context_segments,ms_segments,official_answer,official_guidance,marks,topic_auto,difficulty,manually_edited,formula_review,updated_at) VALUES(?,?,'1-manual',NULL,'1',1,?,?,'[]','[]','','',NULL,'[]','unknown',1,1,?)",(qid,pid,stem,S.js(segments),stamp))
            qp=conn.execute('SELECT file_hash FROM source_files WHERE id=?',(p['qp_file_id'],)).fetchone()
            ms=conn.execute('SELECT file_hash FROM source_files WHERE id=?',(p['ms_file_id'],)).fetchone()
            signature=f"{qp['file_hash']}:{ms['file_hash'] if ms else ''}:{S.INDEX_VERSION}"
            conn.execute("INSERT INTO paper_index VALUES(?,?,'manual',NULL,?) ON CONFLICT(paper_id) DO UPDATE SET signature=excluded.signature,status='manual',error=NULL,updated_at=excluded.updated_at",(pid,signature,stamp))
        return S.question_for(qid,u)

    @app.post('/api/questions/{qid}/split')
    def split(request:Request,qid:str,body:Split):
        u=S.user(request);q=S.question_for(qid,u,True)
        if not q['leaf']: raise HTTPException(400,'请选择最小小题进行拆分')
        return replace(u,[q],body.parts,'split')

    @app.post('/api/layout/merge')
    def merge(request:Request,body:Merge):
        u=S.user(request)
        if len(set(body.question_ids))!=len(body.question_ids): raise HTTPException(400,'不能重复选择同一道题')
        old=[S.question_for(q,u,True) for q in body.question_ids]
        if any(not q['leaf'] for q in old): raise HTTPException(400,'只能合并最小小题')
        if len({q['root_label'] for q in old})!=1: raise HTTPException(400,'请选择同一大题内的小题合并，以保留共同题干')
        def regions(key):
            result=[]
            for q in old:
                for seg in q[key]:
                    if seg not in result: result.append(seg)
            return sorted(result,key=lambda s:(s['page'],s['rect'][1],s['rect'][0]))
        marks=sum(q['marks'] for q in old) if all(q['marks'] is not None for q in old) else None
        return replace(u,old,[Part(label=body.label,segments=regions('segments'),context_segments=regions('context_segments'),ms_segments=regions('ms_segments'),marks=marks)],'merge')

    @app.get('/api/layout/revisions')
    def revisions(request:Request,paper_id:str):
        u=S.user(request);S.paper_for(paper_id,u,True)
        with S.C.connect() as conn:
            rows=[dict(r) for r in conn.execute('SELECT id,kind,created_at,undone FROM layout_revisions WHERE paper_id=? AND user_id=? ORDER BY rowid DESC LIMIT 20',(paper_id,u['id']))]
        return {'revisions':rows}

    @app.post('/api/layout/revisions/{rid}/undo')
    def undo(request:Request,rid:str):
        u=S.user(request)
        with S.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            r=conn.execute('SELECT * FROM layout_revisions WHERE id=? AND user_id=?',(rid,u['id'])).fetchone()
            if not r or r['undone']: raise HTTPException(404,'此操作不存在或已撤销')
            S.paper_for(r['paper_id'],u,True)
            latest=conn.execute('SELECT id FROM layout_revisions WHERE paper_id=? AND undone=0 ORDER BY rowid DESC LIMIT 1',(r['paper_id'],)).fetchone()
            if latest['id']!=rid: raise HTTPException(409,'请先撤销最近一次拆分或合并')
            for qid in json.loads(r['created_ids']):
                q=conn.execute('SELECT active,updated_at FROM questions WHERE id=?',(qid,)).fetchone()
                if not q or not q['active'] or q['updated_at']!=r['created_at']: raise HTTPException(409,'新题目已有后续编辑，不能直接撤销')
            for qid in json.loads(r['created_ids']): conn.execute('UPDATE questions SET active=0,manually_edited=1 WHERE id=?',(qid,))
            for old in json.loads(r['before_rows']):
                fields=[k for k in old if k!='id']
                conn.execute('UPDATE questions SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',[old[k] for k in fields]+[old['id']])
            conn.execute('UPDATE layout_revisions SET undone=1 WHERE id=?',(rid,))
        return {'ok':True}
