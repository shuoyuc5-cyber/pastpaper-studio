"""Public enrollment, recovery and MFA. LAN accounts use their existing flows."""
import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import public_mode, public_mail
from .account_security import password_hash
from .security import client_peer, rate_limit


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS public_verified(
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, email TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS public_links(
        digest TEXT PRIMARY KEY, purpose TEXT NOT NULL, subject TEXT NOT NULL, email TEXT NOT NULL,
        invitation TEXT, expires_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS public_links_expiry ON public_links(expires_at);
    CREATE TABLE IF NOT EXISTS public_mfa_used(
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, counter INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS public_mfa_sessions(
        token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE
    );
    """)
    public_mail.initialize(conn)


def verified(conn, user_id, email):
    return email and conn.execute('SELECT 1 FROM public_verified WHERE user_id=? AND email=?',
                                  (user_id, email)).fetchone()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def validate_password(value):
    if len(value) < 12:
        raise HTTPException(400, 'Use at least 12 characters for a public account password.')


def totp_secret():
    try:
        path = Path(os.environ['PASTPAPER_ADMIN_TOTP_FILE'])
        if path.stat().st_mode & 0o077:
            raise ValueError('TOTP key file must be private')
        key = base64.b32decode(path.read_text().strip())
        if len(key) < 20:
            raise ValueError('TOTP seed is too short')
        return key
    except (KeyError, OSError, binascii.Error, ValueError) as exc:
        raise RuntimeError('A readable, private administrator TOTP seed file is required') from exc


def code_at(key, counter):
    mac = hmac.digest(key, counter.to_bytes(8, 'big'), 'sha1')
    offset = mac[-1] & 15
    return f'{(int.from_bytes(mac[offset:offset + 4], "big") & 0x7fffffff) % 1_000_000:06d}'


def verify_mfa(conn, user_id, code):
    if not code:
        raise HTTPException(428, 'Enter the code from your authenticator.')
    key = totp_secret()
    current = int(time.time()) // 30
    for counter in (current, current - 1, current + 1):
        if hmac.compare_digest(code_at(key, counter), code):
            result = conn.execute("""INSERT INTO public_mfa_used VALUES(?,?)
                ON CONFLICT(user_id) DO UPDATE SET counter=excluded.counter
                WHERE excluded.counter>public_mfa_used.counter""", (user_id, counter))
            if result.rowcount:
                return
    raise HTTPException(401, 'Authenticator code is invalid, expired or already used.')


class Enrollment(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r'^[\w\u4e00-\u9fff .-]+$')
    email: str = Field(max_length=254)
    invite_code: str = Field(min_length=1, max_length=128, repr=False)


class EmailRequest(BaseModel):
    email: str = Field(max_length=254)


class LinkPassword(BaseModel):
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$', repr=False)
    password: str = Field(min_length=12, max_length=128, repr=False)


def issue(conn, purpose, subject, email, invitation=None):
    if public_mail.capturing() and not email.endswith('@example.test'):
        raise HTTPException(400, 'Use an example.test address in the local test environment.')
    now = int(time.time())
    conn.execute('DELETE FROM public_links WHERE expires_at<=?', (now,))
    # Keep a delivered link valid across subsequent requests and prevent mail flooding.
    if conn.execute("""SELECT 1 FROM public_links WHERE purpose=? AND subject=? AND email=?
                    AND invitation IS ? AND expires_at>?""", (purpose, subject, email, invitation, now)).fetchone():
        return
    token = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO public_links VALUES(?,?,?,?,?,?)',
                 (digest(token), purpose, subject, email, invitation, now + 1800))
    label = 'Set up your PastPaper Studio account' if purpose != 'reset' else 'Reset your PastPaper Studio password'
    public_mail.enqueue(conn, email, label, f'{label}\n\n{public_mode.ORIGIN}/#account={token}\n\nLink expires in 30 minutes.')


def provisioned(conn, account):
    if account['email']:
        issue(conn, 'verify', account['id'], account['email'])


def install(app, studio):
    def email_limit(request, value, scope):
        rate_limit(f'{scope}-peer:{client_peer(request)}', 12, 600)
        email = studio.checked_email(value)
        rate_limit(f'{scope}-email:{digest(email)}', 5, 600)
        return email

    @app.post('/api/auth/public-register', status_code=202)
    def enroll(request: Request, body: Enrollment):
        email = email_limit(request, body.email, 'enroll')
        username = body.username.strip()
        if len(username) < 2:
            raise HTTPException(400, 'Enter a name with at least two characters.')
        invite = digest(body.invite_code.strip())
        with studio.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM invitations WHERE token_hash=? AND used_at IS NULL AND expires_at>?',
                                (invite, time.time())).fetchone():
                raise HTTPException(403, 'Registration requires a valid invitation.')
            prior = conn.execute('SELECT email FROM public_links WHERE invitation=? AND expires_at>?', (invite,time.time())).fetchone()
            if not prior and not conn.execute('SELECT 1 FROM account_emails WHERE email=?', (email,)).fetchone():
                issue(conn, 'enroll', username, email, invite)
        return {'accepted': True}

    @app.post('/api/auth/forgot-password', status_code=202)
    def forgot(request: Request, body: EmailRequest):
        email = email_limit(request, body.email, 'forgot')
        with studio.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            account = conn.execute("""SELECT u.id FROM account_emails e JOIN public_verified v ON v.user_id=e.user_id AND v.email=e.email
                JOIN users u ON u.id=e.user_id LEFT JOIN account_access a ON a.user_id=u.id
                WHERE e.email=? AND u.role IN ('student','teacher') AND COALESCE(a.enabled,1)=1""", (email,)).fetchone()
            if account:
                issue(conn, 'reset', account['id'], email)
        return {'accepted': True}

    @app.post('/api/admin/accounts/{user_id}/setup-link', status_code=202)
    def managed_reset(request: Request, user_id: str):
        actor = studio.admin(request)
        rate_limit('managed-link:' + actor['id'], 20, 600)
        with studio.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("""SELECT e.email, v.email AS verified FROM users u
                JOIN account_emails e ON e.user_id=u.id LEFT JOIN public_verified v ON v.user_id=u.id AND v.email=e.email
                LEFT JOIN account_access a ON a.user_id=u.id WHERE u.id=? AND u.role IN ('teacher','student')
                AND COALESCE(a.enabled,1)=1""", (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Enabled teacher or student email not found.')
            issue(conn, 'reset' if row['verified'] else 'verify', user_id, row['email'])
        return {'accepted': True}

    @app.post('/api/auth/complete-link')
    def complete(request: Request, body: LinkPassword):
        rate_limit('complete-peer:' + client_peer(request), 20, 600)
        token = digest(body.token)
        lookup = 'SELECT * FROM public_links WHERE digest=? AND expires_at>?'
        with studio.C.connect() as conn:
            if not conn.execute(lookup, (token, time.time())).fetchone():
                raise HTTPException(400, 'This link is invalid or expired.')
        encoded = password_hash(body.password)
        with studio.C.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(lookup, (token, time.time())).fetchone()
            if not row:
                raise HTTPException(400, 'This link is invalid or expired.')
            if row['purpose'] == 'enroll':
                used = conn.execute('UPDATE invitations SET used_at=? WHERE token_hash=? AND used_at IS NULL AND expires_at>?',
                                    (time.time(), row['invitation'], time.time()))
                if not used.rowcount:
                    raise HTTPException(400, 'This invitation is invalid or already used.')
                account = studio.insert_account(conn, studio.AccountCredentials(username=row['subject'], email=row['email'],
                                                 password=body.password), 'student', encoded)
                identity = account['id']
            else:
                identity = row['subject']
                account = conn.execute("""SELECT u.id FROM users u JOIN account_emails e ON u.id=e.user_id
                    LEFT JOIN account_access a ON a.user_id=u.id WHERE u.id=? AND e.email=?
                    AND u.role IN ('teacher','student') AND COALESCE(a.enabled,1)=1""", (identity, row['email'])).fetchone()
                if not account:
                    raise HTTPException(400, 'This link is invalid or expired.')
                conn.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, identity))
                conn.execute('DELETE FROM sessions WHERE user_id=?', (identity,))
            conn.execute('INSERT INTO public_verified VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email',
                         (identity, row['email']))
            conn.execute('DELETE FROM public_links WHERE digest=? OR (subject=? AND email=?)', (token, identity, row['email']))
        return {'ok': True}
