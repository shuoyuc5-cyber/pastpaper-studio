"""Published assignments and transactional student attempts."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, model_validator

from . import public_mail, public_mode, pdf_sandbox
from .classroom import ClassCode, ClassroomError, ShortText, class_for, new_code, rate_code, transaction
from .security import classroom_upload_limit, rate_limit, heavy_operation

IMPORT_SLOTS = threading.BoundedSemaphore(2)
FORMATS = {
    'application/pdf':'pdf', 'image/jpeg':'jpeg', 'image/png':'png',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx',
}


def extract_document(data, kind):
    if not IMPORT_SLOTS.acquire(blocking=False):
        raise ClassroomError(429,'Document processing is busy. Try again shortly.','文件解析繁忙，请稍后再试。')
    try:
        if public_mode.ORIGIN:
            try:
                return pdf_sandbox.run('class-import',kind,payload=data,timeout=35)
            except pdf_sandbox.SandboxFailure as error:
                raise ClassroomError(422,'This document could not be extracted. Check the file and OCR setup.',
                                     '无法提取此文件，请检查格式、页数和 OCR 安装。') from error
        with tempfile.TemporaryDirectory(prefix='pastpaper-class-import-') as directory:
            source=Path(directory)/('source.'+kind)
            source.write_bytes(data)
            try:
                result=subprocess.run([sys.executable,'-m','app.class_import',str(source),kind],
                                      cwd=Path(__file__).resolve().parents[1],
                                      env={**{key:os.environ[key] for key in ('PATH','TESSDATA_PREFIX','TMPDIR') if key in os.environ},
                                           'OMP_THREAD_LIMIT':'1'},
                                      stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=35,check=True)
                return json.loads(result.stdout)
            except (subprocess.SubprocessError, ValueError) as error:
                raise ClassroomError(422,'This document could not be extracted. Check the file and OCR setup.',
                                     '无法提取此文件，请检查格式、页数和 OCR 安装。') from error
    finally:
        IMPORT_SLOTS.release()


def initialize_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS class_assignments (
      id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
      version INTEGER NOT NULL, previous_id TEXT REFERENCES class_assignments(id),
      title TEXT NOT NULL, questions TEXT NOT NULL, rules TEXT NOT NULL,
      code TEXT UNIQUE, published_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS class_assignments_class ON class_assignments(class_id, published_at);
    CREATE UNIQUE INDEX IF NOT EXISTS class_assignments_revision ON class_assignments(previous_id) WHERE previous_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS class_attempts (
      id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES class_assignments(id) ON DELETE CASCADE,
      student_id TEXT REFERENCES users(id) ON DELETE SET NULL, number INTEGER NOT NULL,
      order_json TEXT NOT NULL, answers TEXT NOT NULL, grades TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 0, started_at INTEGER NOT NULL, submitted_at INTEGER,
      UNIQUE(assignment_id,student_id,number)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS class_attempt_open ON class_attempts(assignment_id,student_id)
      WHERE submitted_at IS NULL;
    CREATE TABLE IF NOT EXISTS class_grade_audit (
      id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES class_attempts(id) ON DELETE CASCADE,
      grader_id TEXT REFERENCES users(id) ON DELETE SET NULL, position INTEGER NOT NULL,
      before_grade TEXT NOT NULL, after_grade TEXT NOT NULL, created_at TEXT NOT NULL
    );
    """)


AnswerText = Annotated[str, StringConstraints(max_length=4000)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
QuestionType = Literal['single','multiple','boolean','fill','number','short']


class Question(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    kind: QuestionType = 'short'
    marks: int = Field(ge=1, le=100)
    options: list[OptionText] = Field(default_factory=list, max_length=12)
    accepted: list[AnswerText] = Field(default_factory=list, max_length=15)
    topic: str = Field(default='', max_length=100)
    case_sensitive: bool = False
    ignore_punctuation: bool = False
    tolerance: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    partial_credit: bool = False

    @model_validator(mode='after')
    def validate_key(self):
        if self.kind in ('single','multiple','boolean'):
            valid = ['true', 'false'] if self.kind=='boolean' else [str(i) for i in range(len(self.options))]
            if len(valid)<2 or not self.accepted or not set(self.accepted).issubset(valid):
                raise ValueError('Invalid choice key')
            if self.kind!='multiple' and len(self.accepted)!=1:
                raise ValueError('Only one correct choice is allowed')
        elif self.kind=='fill' and (not self.accepted or not all(a.strip() for a in self.accepted)):
            raise ValueError('Accepted text answers are required')
        elif self.kind=='number' and (not self.accepted or any(decimal_answer(a) is None for a in self.accepted)):
            raise ValueError('Accepted numerical answers are required')
        return self


class Rules(BaseModel):
    opens_at: int | None = Field(default=None, ge=0, le=4102444800)
    deadline: int | None = Field(default=None, ge=0, le=4102444800)
    minutes: int | None = Field(default=None, ge=1, le=600)
    attempts: int = Field(default=1, ge=1, le=10)
    allow_late: bool = False
    shuffle_questions: bool = False
    shuffle_options: bool = False
    show_results: bool = True
    reveal_answers: bool = False
    leaderboard: bool = False

    @model_validator(mode='after')
    def dates(self):
        if self.deadline and self.opens_at and self.deadline <= self.opens_at:
            raise ValueError('Deadline must be after opening time')
        return self


class Draft(BaseModel):
    title: ShortText
    questions: list[Question] = Field(min_length=1, max_length=60)
    rules: Rules = Field(default_factory=Rules)
    previous_id: str | None = Field(default=None, max_length=64)


class BankRequest(BaseModel):
    count: int = Field(ge=1, le=60)
    total_marks: int | None = Field(default=None, ge=1, le=300)
    subject_code: str = Field(default='', max_length=10)
    topic: str = Field(default='', max_length=100)
    difficulty: Literal['','easy','medium','hard'] = ''


Answer = AnswerText | Annotated[list[OptionText], Field(max_length=12)]


class Answers(BaseModel):
    revision: int = Field(ge=0)
    answers: dict[int, Answer] = Field(max_length=60)


class Grade(BaseModel):
    marks: float = Field(ge=0, le=100, allow_inf_nan=False)
    feedback: str = Field(default='', max_length=3000)


def decimal_answer(value):
    value = value.strip()
    if len(value)>80 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?', value):
        return None
    try:
        number = Decimal(value)
        return number if abs(number.adjusted())<=300 else None
    except InvalidOperation:
        return None


def grade_question(question, answer):
    kind, marks = question['kind'], question['marks']
    if kind=='short':
        return None
    key = question['accepted']
    if kind=='multiple':
        selected = set(answer) if isinstance(answer,list) else set()
        correct = set(key)
        if question['partial_credit']:
            return round(marks * max(0, len(selected & correct)-len(selected-correct))/len(correct), 2)
        return marks if selected==correct else 0
    if not isinstance(answer, str):
        return 0
    if kind in ('single', 'boolean'):
        return marks if answer in key else 0
    if kind=='number':
        value = decimal_answer(answer)
        tolerance = Decimal(str(question['tolerance']))
        return marks if value is not None and any(abs(value-decimal_answer(a))<=tolerance for a in key) else 0
    def normalized(text):
        text = unicodedata.normalize('NFKC',text)
        if question['ignore_punctuation']:
            text = ''.join(c for c in text if not unicodedata.category(c).startswith('P'))
        text = ' '.join(text.split())
        return text if question['case_sensitive'] else text.casefold()
    return marks if any(normalized(answer)==normalized(a) for a in key) else 0


def assignment_for(conn, assignment_id, actor, *, manage=False):
    row = conn.execute('SELECT * FROM class_assignments WHERE id=?', (assignment_id,)).fetchone()
    if not row:
        raise ClassroomError(404, 'Assignment not found.', '找不到此作业。')
    try:
        class_for(conn, row['class_id'], actor, manage=manage)
    except ClassroomError as error:
        if error.status_code != 404:
            raise
        raise ClassroomError(404, 'Assignment not found.', '找不到此作业。') from error
    if not manage and (not row['published_at'] or row['published_at'] > int(time.time())):
        raise ClassroomError(404, 'Assignment not found.', '找不到此作业。')
    return row


def summary(row, include_code=False):
    return {key:row[key] for key in ('id','class_id','title','version','published_at')} | {
        'rules':json.loads(row['rules']), **({'code':row['code']} if include_code else {}),
    }


def attempt_for(conn, assignment_id, attempt_id, actor=None):
    row = conn.execute('SELECT * FROM class_attempts WHERE id=? AND assignment_id=?',
                       (attempt_id,assignment_id)).fetchone()
    if not row or (actor is not None and row['student_id']!=actor['id']):
        raise ClassroomError(404, 'Attempt not found.', '找不到此答卷。')
    return row


def attempt_deadline(rules, started_at):
    values = []
    if rules['deadline'] and not rules['allow_late']:
        values.append(rules['deadline'])
    if rules['minutes']:
        values.append(started_at + rules['minutes']*60)
    return min(values) if values else None


def score_metrics(questions, grades):
    pairs = [(question['marks'], grades.get(str(i),{}).get('marks')) for i,question in enumerate(questions)]
    graded = [(maximum, value) for maximum,value in pairs if value is not None]
    available = sum(maximum for maximum,_ in graded)
    marks = round(sum(value for _,value in graded),2)
    return {'marks':marks,'available_marks':available,'total_marks':sum(maximum for maximum,_ in pairs),
            'graded':len(graded),'pending':len(pairs)-len(graded),
            'accuracy':round(100*sum(maximum==value for maximum,value in graded)/len(graded),2) if graded else None,
            'percentage':round(100*marks/available,2) if available else None}


def student_attempt(row, assignment):
    questions, rules = json.loads(assignment['questions']), json.loads(assignment['rules'])
    order = json.loads(row['order_json'])
    student_questions = []
    for position in order['questions']:
        q = questions[position]
        item = {key:q[key] for key in ('text','kind','marks','topic')}
        item['position'] = position
        item['options'] = [{'id':str(i),'text':q['options'][i]} for i in order['options'][str(position)]]
        if row['submitted_at'] and rules['show_results'] and rules['reveal_answers'] and q['kind']!='short':
            item['accepted'] = q['accepted']
        student_questions.append(item)
    result = {key:row[key] for key in ('id','revision','started_at','submitted_at','number')}
    result.update(questions=student_questions, answers=json.loads(row['answers']),
                  expires_at=attempt_deadline(rules,row['started_at']))
    if row['submitted_at'] and rules['show_results']:
        result['grades'] = json.loads(row['grades'])
        result['metrics'] = score_metrics(questions,result['grades'])
    return result


def check_student(conn, assignment, actor):
    active = conn.execute(
        "SELECT 1 FROM class_memberships WHERE class_id=? AND user_id=? AND status='active'",
        (assignment['class_id'],actor['id'])
    ).fetchone()
    if not active:
        raise ClassroomError(404, 'Assignment not found.', '找不到此作业。')


def install(app, studio):
    @app.post('/api/classroom/classes/{class_id}/document-import')
    async def import_document(request: Request, class_id: str):
        actor=studio.user(request)
        with studio.C.connect() as conn:
            class_for(conn,class_id,actor,manage=True)
        try:
            rate_limit('class-document:'+actor['id'],8)
        except HTTPException as error:
            raise ClassroomError(error.status_code,'Too many document imports. Try again shortly.','文件导入过于频繁，请稍后再试。') from error
        kind=FORMATS.get(request.headers.get('content-type','').split(';')[0])
        if not kind:
            raise ClassroomError(415,'Choose a PDF, DOCX, JPEG or PNG file.','请选择 PDF、DOCX、JPEG 或 PNG 文件。')
        try:
            data=await studio.bounded_body(request,classroom_upload_limit())
        except HTTPException as error:
            raise ClassroomError(error.status_code,'The document exceeds the upload limit.','文件超过上传大小限制。') from error
        return {'questions':await run_in_threadpool(extract_document,data,kind)}

    @app.get('/api/classroom/classes/{class_id}/assignments')
    def assignments(request: Request, class_id: str, manage: bool=False):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            class_for(conn,class_id,actor,manage=manage)
            rows = conn.execute('SELECT * FROM class_assignments WHERE class_id=? ' +
                                ('' if manage else 'AND published_at<=? ') + 'ORDER BY rowid DESC',
                                (class_id,) if manage else (class_id,int(time.time()))).fetchall()
        return {'assignments':[summary(row,manage) for row in rows]}

    @app.post('/api/classroom/classes/{class_id}/generate')
    def generate(request: Request, class_id: str, body: BankRequest):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            class_for(conn,class_id,actor,manage=True)
        try:
            with heavy_operation():
                selected = studio.select_builder_questions(studio.AutoBuilder(**body.model_dump()),actor)
        except HTTPException as error:
            if error.status_code!=400:
                raise
            raise ClassroomError(400,'The authorized question bank cannot meet these constraints.', '有权使用的已核对题目不足，请调整组卷条件。') from error
        questions = []
        for question in selected:
            if not question['marks'] or not question['stem'].strip():
                raise ClassroomError(400,'A selected question needs text and marks before it can be assigned.', '选中的题目需要补齐正文与分值。')
            tags = json.loads(question['tags']) or json.loads(question['topic_auto'])
            questions.append(Question(text=question['stem'][:8000],marks=question['marks'],topic=tags[0][:100] if tags else '').model_dump())
        return {'questions':questions}

    @app.post('/api/classroom/classes/{class_id}/assignments',status_code=201)
    def create(request: Request, class_id: str, body: Draft):
        actor = studio.user(request)
        with transaction(studio) as conn:
            room = class_for(conn,class_id,actor,manage=True)
            if room['archived']:
                raise ClassroomError(409,'This class is archived.','此班级已归档。')
            version = 1
            if body.previous_id:
                previous = assignment_for(conn,body.previous_id,actor,manage=True)
                if previous['class_id']!=class_id or not previous['published_at']:
                    raise ClassroomError(409,'Version must follow a published assignment in this class.','只能从同班级的已发布作业创建新版本。')
                if conn.execute('SELECT 1 FROM class_assignments WHERE previous_id=?',(body.previous_id,)).fetchone():
                    raise ClassroomError(409,'A later version already exists.','此作业已有后续版本。')
                version = previous['version']+1
            identity = studio.uid()
            conn.execute('INSERT INTO class_assignments VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                         (identity,class_id,version,body.previous_id,body.title,
                          studio.js([q.model_dump() for q in body.questions]),studio.js(body.rules.model_dump())))
            row = conn.execute('SELECT * FROM class_assignments WHERE id=?',(identity,)).fetchone()
        return summary(row,True)

    @app.get('/api/classroom/assignments/{assignment_id}')
    def detail(request: Request, assignment_id: str, manage: bool=False):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            row = assignment_for(conn,assignment_id,actor,manage=manage)
            if manage:
                return {**summary(row,True),'questions':json.loads(row['questions'])}
            check_student(conn,row,actor)
            attempts = conn.execute(
                'SELECT * FROM class_attempts WHERE assignment_id=? AND student_id=? ORDER BY number DESC',
                (assignment_id,actor['id'])
            ).fetchall()
        return {**summary(row),'attempts':[student_attempt(a,row) for a in attempts]}

    @app.put('/api/classroom/assignments/{assignment_id}')
    def update(request: Request, assignment_id: str, body: Draft):
        actor = studio.user(request)
        with transaction(studio) as conn:
            row = assignment_for(conn,assignment_id,actor,manage=True)
            if row['published_at']:
                raise ClassroomError(409,'Published versions are immutable. Create a new version.','已发布版本已锁定，请创建新版本。')
            conn.execute('UPDATE class_assignments SET title=?, questions=?,rules=? WHERE id=?',
                         (body.title,studio.js([q.model_dump() for q in body.questions]),studio.js(body.rules.model_dump()),assignment_id))
            row = conn.execute('SELECT * FROM class_assignments WHERE id=?',(assignment_id,)).fetchone()
        return summary(row,True)

    @app.post('/api/classroom/assignments/{assignment_id}/publish')
    def publish(request: Request, assignment_id: str):
        actor = studio.user(request)
        with transaction(studio) as conn:
            row = assignment_for(conn,assignment_id,actor,manage=True)
            if not row['published_at']:
                if class_for(conn,row['class_id'],actor,manage=True)['archived']:
                    raise ClassroomError(409,'This class is archived.','此班级已归档。')
                rules = json.loads(row['rules'])
                now = int(time.time())
                opens = max(now,rules['opens_at'] or now)
                if rules['deadline'] and rules['deadline']<=opens:
                    raise ClassroomError(409,'The deadline must be after publication.','截止时间必须晚于发布时间。')
                code = new_code(conn,'class_assignments','code',prefix='A-')
                conn.execute('UPDATE class_assignments SET code=?, published_at=? WHERE id=?',(code,opens,assignment_id))
                row = conn.execute('SELECT * FROM class_assignments WHERE id=?',(assignment_id,)).fetchone()
                public_mail.assignment(conn, row['class_id'], row['title'], opens)
        return summary(row,True)

    @app.post('/api/classroom/assignment-code')
    def by_code(request: Request, body: ClassCode):
        actor = studio.user(request)
        rate_code(request,actor)
        code=body.code.strip().upper()
        with studio.C.connect() as conn:
            row = conn.execute('SELECT id FROM class_assignments WHERE code=?',(code,)).fetchone()
            if not row:
                raise ClassroomError(404,'Assignment not found.','找不到此作业。')
            assignment = assignment_for(conn,row['id'],actor)
            check_student(conn,assignment,actor)
        return summary(assignment)

    @app.post('/api/classroom/assignments/{assignment_id}/attempts')
    def begin(request: Request, assignment_id: str):
        actor = studio.user(request)
        with transaction(studio) as conn:
            assignment = assignment_for(conn,assignment_id,actor)
            check_student(conn,assignment,actor)
            if class_for(conn,assignment['class_id'],actor)['archived']:
                raise ClassroomError(409,'This class is archived.','此班级已归档。')
            rules, questions = json.loads(assignment['rules']), json.loads(assignment['questions'])
            attempts = conn.execute(
                'SELECT * FROM class_attempts WHERE assignment_id=? AND student_id=? ORDER BY number DESC',
                (assignment_id,actor['id'])).fetchall()
            if attempts and not attempts[0]['submitted_at']:
                return student_attempt(attempts[0],assignment)
            if len(attempts)>=rules['attempts']:
                raise ClassroomError(409,'No attempts remain.','已用完作答次数。')
            started = int(time.time())
            deadline = attempt_deadline(rules,started)
            if deadline is not None and started>=deadline:
                raise ClassroomError(409,'The assignment deadline has passed.','作业已超过截止时间。')
            order = list(range(len(questions)))
            options = {str(i):list(range(len(q['options']))) for i,q in enumerate(questions)}
            rng=secrets.SystemRandom()
            if rules['shuffle_questions']:rng.shuffle(order)
            if rules['shuffle_options']:
                for values in options.values():rng.shuffle(values)
            attempt_id=studio.uid()
            conn.execute('INSERT INTO class_attempts VALUES(?,?,?,?,?,?,?,0,?,NULL)',
                         (attempt_id,assignment_id,actor['id'],len(attempts)+1,
                          studio.js({'questions':order,'options':options}),'{}','{}',started))
            row=attempt_for(conn,assignment_id,attempt_id,actor)
        return student_attempt(row,assignment)

    def write_attempt(request, assignment_id, attempt_id, body, submit):
        actor = studio.user(request)
        with transaction(studio) as conn:
            assignment = assignment_for(conn,assignment_id,actor)
            check_student(conn,assignment,actor)
            row = attempt_for(conn,assignment_id,attempt_id,actor)
            if row['submitted_at']:
                if submit:return student_attempt(row,assignment)
                raise ClassroomError(409,'This attempt is already submitted.','此答卷已提交。')
            if class_for(conn,assignment['class_id'],actor)['archived']:
                raise ClassroomError(409,'This class is archived.','此班级已归档。')
            if row['revision']!=body.revision:
                raise ClassroomError(409,'Answers changed elsewhere. Reopen the attempt before retrying.','答卷已在其他页面变更，请重新打开。')
            deadline = attempt_deadline(json.loads(assignment['rules']),row['started_at'])
            current = int(time.time())
            if deadline is not None and current>=deadline:
                raise ClassroomError(409,'The time to submit has expired.','作答时间已结束。')
            questions = json.loads(assignment['questions'])
            if any(i<0 or i>=len(questions) for i in body.answers):
                raise ClassroomError(400,'Invalid question index.','题号无效。')
            answers = {str(i):answer for i,answer in body.answers.items()}
            grades = {}
            if submit:
                grades = {str(i):{'marks':grade_question(q,answers.get(str(i))), 'feedback':''}
                          for i,q in enumerate(questions)}
            conn.execute('UPDATE class_attempts SET answers=?,grades=?,submitted_at=?,revision=revision+1 WHERE id=?',
                         (studio.js(answers),studio.js(grades),current if submit else None,attempt_id))
            row = attempt_for(conn,assignment_id,attempt_id,actor)
        return student_attempt(row,assignment)

    @app.put('/api/classroom/assignments/{assignment_id}/attempts/{attempt_id}')
    def save(request: Request, assignment_id: str, attempt_id: str, body: Answers):
        return write_attempt(request,assignment_id,attempt_id,body,False)

    @app.post('/api/classroom/assignments/{assignment_id}/attempts/{attempt_id}/submit')
    def submit(request: Request, assignment_id: str, attempt_id: str, body: Answers):
        return write_attempt(request,assignment_id,attempt_id,body,True)

    @app.get('/api/classroom/assignments/{assignment_id}/submissions')
    def submissions(request: Request, assignment_id: str):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            assignment = assignment_for(conn,assignment_id,actor,manage=True)
            questions = json.loads(assignment['questions'])
            rows = conn.execute('SELECT a.*,u.username FROM class_attempts a LEFT JOIN users u ON u.id=a.student_id '
                                'WHERE a.assignment_id=? AND a.submitted_at IS NOT NULL ORDER BY a.submitted_at DESC,a.id',
                                (assignment_id,)).fetchall()
        return {'submissions':[{
            'id':row['id'],'username':row['username'],'number':row['number'],'submitted_at':row['submitted_at'],
            'answers':json.loads(row['answers']),'grades':json.loads(row['grades']),
            'metrics':score_metrics(questions,json.loads(row['grades']))
        } for row in rows]}

    @app.get('/api/classroom/classes/{class_id}/analytics')
    def analytics(request: Request, class_id: str, period: Literal['7','30','all']='all'):
        actor=studio.user(request)
        start=0 if period=='all' else int(time.time())-int(period)*86400
        with studio.C.connect() as conn:
            class_for(conn,class_id,actor,manage=True)
            students=conn.execute("SELECT COUNT(*) FROM class_memberships WHERE class_id=? AND status='active'",(class_id,)).fetchone()[0]
            published=conn.execute('SELECT id,title,questions FROM class_assignments WHERE class_id=? AND published_at BETWEEN ? AND ? ORDER BY published_at DESC,id',
                                   (class_id,start,int(time.time()))).fetchall()
            attempts=conn.execute(
                'SELECT a.assignment_id,a.student_id,a.grades FROM class_attempts a '
                'JOIN class_assignments d ON d.id=a.assignment_id '
                "JOIN class_memberships m ON m.class_id=d.class_id AND m.user_id=a.student_id AND m.status='active' "
                'WHERE d.class_id=? AND d.published_at BETWEEN ? AND ? AND a.submitted_at IS NOT NULL '
                'ORDER BY a.number DESC',
                (class_id,start,int(time.time())),
            ).fetchall()
        by_assignment={}
        for row in attempts:
            by_assignment.setdefault(row['assignment_id'],{}).setdefault(row['student_id'],json.loads(row['grades']))
        class_topics={}
        statistics=[]
        for row in published:
            questions=json.loads(row['questions'])
            grades=list(by_assignment.get(row['id'],{}).values())
            metrics=[score_metrics(questions,item) for item in grades]
            scores=[item['percentage'] for item in metrics if item['percentage'] is not None]
            accuracies=[item['accuracy'] for item in metrics if item['accuracy'] is not None]
            per_question=[]
            for position,q in enumerate(questions):
                values=[grade.get(str(position),{}).get('marks') for grade in grades]
                graded=[value for value in values if value is not None]
                correct=sum(value==q['marks'] for value in graded)
                per_question.append({'position':position+1,'graded':len(graded),
                                     'accuracy':round(correct/len(graded)*100,2) if graded else None})
                if q['topic'] and graded:
                    topic=class_topics.setdefault(q['topic'],{'topic':q['topic'],'correct':0,'graded':0})
                    topic['correct']+=correct
                    topic['graded']+=len(graded)
            statistics.append({'id':row['id'],'title':row['title'],'completed':len(grades),
                               'completion':round(100*len(grades)/students,2) if students else None,
                               'average_score':round(sum(scores)/len(scores),2) if scores else None,
                               'average_accuracy':round(sum(accuracies)/len(accuracies),2) if accuracies else None,
                               'questions':per_question})
        return {'students':students,'published':len(published),'assignments':statistics,'topics':list(class_topics.values())}

    @app.put('/api/classroom/assignments/{assignment_id}/submissions/{attempt_id}/grades/{position}')
    def grade(request: Request, assignment_id: str, attempt_id: str, position: int, body: Grade):
        actor = studio.user(request)
        with transaction(studio) as conn:
            assignment = assignment_for(conn,assignment_id,actor,manage=True)
            row = attempt_for(conn,assignment_id,attempt_id)
            if row['student_id']==actor['id']:
                raise ClassroomError(403,'You cannot grade your own submission.','不能给自己的答卷评分。')
            questions = json.loads(assignment['questions'])
            if not row['submitted_at'] or not 0<=position<len(questions) or body.marks>questions[position]['marks']:
                raise ClassroomError(400,'Invalid grade for this submission.','分值或答卷状态无效。')
            grades = json.loads(row['grades'])
            key=str(position)
            previous = grades[key]
            grades[key]=body.model_dump()
            conn.execute('UPDATE class_attempts SET grades=? WHERE id=?',(studio.js(grades),attempt_id))
            if previous!=grades[key]:
                conn.execute('INSERT INTO class_grade_audit VALUES(?,?,?,?,?,?,?)',
                             (studio.uid(),attempt_id,actor['id'],position,studio.js(previous),studio.js(grades[key]),studio.now()))
        return score_metrics(questions,grades)

    @app.get('/api/classroom/assignments/{assignment_id}/leaderboard')
    def leaderboard(request: Request, assignment_id: str, manage: bool=False):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            assignment = assignment_for(conn,assignment_id,actor,manage=manage)
            if not manage:
                check_student(conn,assignment,actor)
            rules = json.loads(assignment['rules'])
            if not rules['leaderboard'] or not rules['show_results']:
                raise ClassroomError(404,'Leaderboard is unavailable.','此作业未开放排行榜。')
            questions = json.loads(assignment['questions'])
            rows = conn.execute(
                'SELECT a.student_id,a.grades FROM class_attempts a JOIN class_memberships m '
                "ON m.class_id=? AND m.user_id=a.student_id AND m.status='active' "
                'WHERE a.assignment_id=? AND a.submitted_at IS NOT NULL',(assignment['class_id'],assignment_id)
            ).fetchall()
        best = {}
        for row in rows:
            metrics = score_metrics(questions,json.loads(row['grades']))
            if metrics['pending']:
                continue
            sid=row['student_id']
            if sid not in best or metrics['marks']>best[sid]['marks']:
                best[sid]=metrics
        ranking = sorted(best,key=lambda sid:(-best[sid]['marks'],-(best[sid]['accuracy'] or 0),sid))
        result=[]
        previous=None
        rank=0
        for position,sid in enumerate(ranking,1):
            score=(best[sid]['marks'],best[sid]['accuracy'])
            if score!=previous:rank=position;previous=score
            nickname='Student '+hashlib.sha256((assignment_id+sid).encode()).hexdigest()[:7].upper()
            result.append({'rank':rank,'nickname':nickname,'mine':sid==actor['id'],**best[sid]})
        return {'ranking':result}
