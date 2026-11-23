"""Host-side classes with scoped membership and server-enforced teaching permissions."""
from contextlib import contextmanager
import secrets
import sqlite3
import time
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from .security import rate_limit
from . import public_mode

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TeachingRole = ("admin", "teacher")


def initialize_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS classrooms (
      id TEXT PRIMARY KEY, owner_id TEXT REFERENCES users(id) ON DELETE SET NULL,
      name TEXT NOT NULL, subject TEXT NOT NULL, grade TEXT NOT NULL, description TEXT NOT NULL,
      capacity INTEGER, admission TEXT NOT NULL CHECK(admission IN ('automatic','approval')),
      join_code TEXT UNIQUE NOT NULL, join_enabled INTEGER NOT NULL CHECK(join_enabled IN (0,1)),
      join_expires_at INTEGER, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS classrooms_owner ON classrooms(owner_id, created_at);
    CREATE TABLE IF NOT EXISTS class_memberships (
      class_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      status TEXT NOT NULL CHECK(status IN ('pending','active')),
      created_at TEXT NOT NULL, PRIMARY KEY(class_id, user_id)
    );
    CREATE INDEX IF NOT EXISTS class_memberships_user ON class_memberships(user_id, class_id);
    """)
    if 'archived' not in {row['name'] for row in conn.execute('PRAGMA table_info(classrooms)')}:
        conn.execute("ALTER TABLE classrooms ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")


class ClassroomError(HTTPException):
    def __init__(self, status, en, zh):
        super().__init__(status, en)
        self.zh = zh


async def localize_error(request, error):
    language = request.headers.get('x-studio-language', 'zh-CN')
    return JSONResponse({'detail': error.detail if language == 'en' else error.zh}, status_code=error.status_code)


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ClassroomCreate(BaseModel):
    name: ShortText
    subject: ShortText
    grade: str = Field(default='', max_length=80)
    description: str = Field(default='', max_length=1600)
    capacity: int | None = Field(default=None, ge=1, le=1000)
    admission: Literal['automatic', 'approval'] = 'approval'
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class InviteSettings(BaseModel):
    enabled: bool
    regenerate: bool = False
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    admission: Literal['automatic', 'approval'] | None = None


class ClassCode(BaseModel):
    code: str = Field(min_length=1, max_length=32)


@contextmanager
def transaction(studio):
    with studio.C.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        yield conn


def require_teacher(conn, actor):
    row = conn.execute(
        'SELECT u.role, COALESCE(a.enabled, 1) enabled FROM users u '
        'LEFT JOIN account_access a ON a.user_id=u.id WHERE u.id=?', (actor['id'],)
    ).fetchone()
    if not row or not row['enabled'] or row['role'] not in TeachingRole:
        raise ClassroomError(403, 'Teacher permissions required.', '此操作需要老师权限。')
    return row['role']


def class_for(conn, class_id, actor, *, manage=False):
    room = conn.execute('SELECT * FROM classrooms WHERE id=?', (class_id,)).fetchone()
    if manage:
        role = require_teacher(conn, actor)
        allowed = room and (role == 'admin' or room['owner_id'] == actor['id'])
    else:
        allowed = room and (actor['role'] == 'admin' or
                            (actor['role'] == 'teacher' and room['owner_id'] == actor['id']) or
                            conn.execute(
                                "SELECT 1 FROM class_memberships WHERE class_id=? AND user_id=? AND status='active'",
                                (class_id, actor['id']),
                            ).fetchone())
    if not allowed:
        raise ClassroomError(404, 'Class not found.', '找不到此班级。')
    return room


def public_class(room):
    return {key: room[key] for key in ('id', 'name', 'subject', 'grade', 'description')}


def invitation_view(room):
    return {**public_class(room), **{key: room[key] for key in (
        'capacity', 'admission', 'join_code', 'join_enabled', 'join_expires_at', 'archived'
    )}}


def new_code(conn, table, column, prefix=''):
    for _ in range(8):
        code = prefix + ''.join(secrets.choice(CODE_ALPHABET) for _ in range(7))
        if not conn.execute(f'SELECT 1 FROM {table} WHERE {column}=?', (code,)).fetchone():
            return code
    raise ClassroomError(503, 'Could not create a code. Try again.', '暂时无法生成班级码，请重试。')


def rate_code(request, actor):
    try:
        rate_limit('class-code-user:' + actor['id'], 20)
        peer = request.headers.get('x-forwarded-for', request.client.host) if request.client.host in ('127.0.0.1', '::1') else request.client.host
        rate_limit('class-code-peer:' + peer, 60)
    except HTTPException as error:
        raise ClassroomError(error.status_code, 'Too many code attempts. Try again shortly.', '尝试次数过多，请稍后再试。') from error


def open_invitation(conn, code):
    row = conn.execute(
        'SELECT * FROM classrooms WHERE join_code=? AND join_enabled=1 AND archived=0 AND '
        '(join_expires_at IS NULL OR join_expires_at>?)',
        (code.strip().upper(), int(time.time()))
    ).fetchone()
    if not row:
        raise ClassroomError(404, 'Class code is invalid, expired or closed.', '班级码无效、已过期或已关闭。')
    return row


def check_capacity(conn, room):
    if room['capacity'] is not None and conn.execute(
        "SELECT COUNT(*) FROM class_memberships WHERE class_id=? AND status='active'", (room['id'],)
    ).fetchone()[0] >= room['capacity']:
        raise ClassroomError(409, 'The class is full.', '此班级人数已满。')


def install(app, studio):
    app.add_exception_handler(ClassroomError, localize_error)

    @app.get('/api/classroom/classes')
    def classes(request: Request):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            if actor['role'] in TeachingRole:
                query = 'SELECT * FROM classrooms WHERE owner_id=?' if actor['role'] == 'teacher' else 'SELECT * FROM classrooms'
                owned = conn.execute(query + ' ORDER BY created_at DESC, id', (actor['id'],) if actor['role']=='teacher' else ()).fetchall()
            else:
                owned = []
            joined = conn.execute(
                'SELECT c.*, m.status FROM class_memberships m JOIN classrooms c ON c.id=m.class_id '
                'WHERE m.user_id=? ORDER BY m.created_at DESC, c.id', (actor['id'],)
            ).fetchall()
        return {'managed': [invitation_view(row) for row in owned],
                'joined': [{**public_class(row), 'status': row['status']} for row in joined]}

    @app.post('/api/classroom/classes', status_code=201)
    def create(request: Request, body: ClassroomCreate):
        actor = studio.user(request)
        with transaction(studio) as conn:
            require_teacher(conn, actor)
            class_id = studio.uid()
            code = new_code(conn, 'classrooms', 'join_code')
            expiration = int(time.time()) + body.expires_in_days * 86400 if body.expires_in_days else None
            conn.execute(
                'INSERT INTO classrooms(id,owner_id,name,subject,grade,description,capacity,admission,join_code,join_enabled,join_expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?)',
                (class_id, actor['id'], body.name, body.subject, body.grade.strip(), body.description.strip(),
                 body.capacity, body.admission, code, expiration, studio.now())
            )
            room = conn.execute('SELECT * FROM classrooms WHERE id=?', (class_id,)).fetchone()
        return invitation_view(room)

    @app.put('/api/classroom/classes/{class_id}/invitation')
    def update_invitation(request: Request, class_id: str, body: InviteSettings):
        actor = studio.user(request)
        with transaction(studio) as conn:
            room = class_for(conn, class_id, actor, manage=True)
            code = new_code(conn, 'classrooms', 'join_code') if body.regenerate else room['join_code']
            expiration = room['join_expires_at']
            if 'expires_in_days' in body.model_fields_set:
                expiration = int(time.time()) + body.expires_in_days * 86400 if body.expires_in_days else None
            conn.execute('UPDATE classrooms SET join_code=?,join_enabled=?,join_expires_at=?,admission=? WHERE id=?',
                         (code, body.enabled, expiration, body.admission or room['admission'], class_id))
            room = conn.execute('SELECT * FROM classrooms WHERE id=?', (class_id,)).fetchone()
        return invitation_view(room)

    if public_mode.ORIGIN:
        @app.put('/api/classroom/classes/{class_id}/archive')
        def archive(request: Request, class_id: str, archived: bool = True):
            actor = studio.user(request)
            with transaction(studio) as conn:
                room = class_for(conn,class_id,actor,manage=True)
                code = new_code(conn,'classrooms','join_code') if room['archived'] and not archived else room['join_code']
                conn.execute('UPDATE classrooms SET archived=?,join_code=? WHERE id=?',(archived,code,class_id))
            return {'archived':archived}

    @app.post('/api/classroom/lookup')
    def lookup(request: Request, body: ClassCode):
        actor = studio.user(request)
        rate_code(request, actor)
        with studio.C.connect() as conn:
            room = open_invitation(conn, body.code)
        return {**public_class(room), 'admission': room['admission']}

    @app.post('/api/classroom/join')
    def join(request: Request, body: ClassCode):
        actor = studio.user(request)
        rate_code(request, actor)
        with transaction(studio) as conn:
            room = open_invitation(conn, body.code)
            if room['owner_id'] == actor['id']:
                raise ClassroomError(409, 'You already manage this class.', '你已经在管理此班级。')
            member = conn.execute(
                'SELECT status FROM class_memberships WHERE class_id=? AND user_id=?', (room['id'], actor['id'])
            ).fetchone()
            if member:
                return {**public_class(room), 'status': member['status']}
            status = 'active' if room['admission'] == 'automatic' else 'pending'
            if status == 'active':
                check_capacity(conn, room)
            conn.execute('INSERT INTO class_memberships VALUES(?,?,?,?)', (room['id'], actor['id'], status, studio.now()))
        return {**public_class(room), 'status': status}

    @app.get('/api/classroom/classes/{class_id}/members')
    def members(request: Request, class_id: str):
        actor = studio.user(request)
        with studio.C.connect() as conn:
            class_for(conn, class_id, actor, manage=True)
            rows = conn.execute(
                'SELECT u.id, u.username, m.status, m.created_at FROM class_memberships m '
                'JOIN users u ON u.id=m.user_id WHERE m.class_id=? ORDER BY m.status DESC, u.username', (class_id,)
            ).fetchall()
        return {'members': [dict(row) for row in rows]}

    @app.put('/api/classroom/classes/{class_id}/members/{user_id}')
    def approve(request: Request, class_id: str, user_id: str):
        actor = studio.user(request)
        with transaction(studio) as conn:
            room = class_for(conn, class_id, actor, manage=True)
            member = conn.execute(
                'SELECT status FROM class_memberships WHERE class_id=? AND user_id=?', (class_id, user_id)
            ).fetchone()
            if not member:
                raise ClassroomError(404, 'Member not found.', '找不到此班级成员。')
            if member['status'] != 'active':
                check_capacity(conn, room)
                conn.execute("UPDATE class_memberships SET status='active' WHERE class_id=? AND user_id=?", (class_id, user_id))
        return {'ok': True}

    @app.delete('/api/classroom/classes/{class_id}/members/{user_id}')
    def remove(request: Request, class_id: str, user_id: str):
        actor = studio.user(request)
        with transaction(studio) as conn:
            class_for(conn, class_id, actor, manage=True)
            conn.execute('DELETE FROM class_memberships WHERE class_id=? AND user_id=?', (class_id, user_id))
        return {'ok': True}
