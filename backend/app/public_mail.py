"""Site-controlled SMTP and a transactionally queued, encrypted outbox."""
import logging
import os
from pathlib import Path
import smtplib
import ssl
import time
import uuid
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import certifi
from cryptography.fernet import Fernet

from . import public_mode
from .account_security import normalize_email

LOG = logging.getLogger(__name__)


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS public_outbox(
        id TEXT PRIMARY KEY, payload BLOB, state TEXT NOT NULL, tries INTEGER NOT NULL,
        scheduled INTEGER NOT NULL, created INTEGER NOT NULL, assignment_class TEXT, student_id TEXT
    )""")
    conn.execute('CREATE INDEX IF NOT EXISTS public_outbox_scheduled ON public_outbox(state,scheduled)')


def private_file(name):
    path = Path(os.environ[name])
    if path.stat().st_mode & 0o077:
        raise ValueError('Secret file must be private')
    return path.read_bytes().strip()


def capturing():
    return public_mode.LOCAL or os.getenv('PASTPAPER_SYNTHETIC_MAIL_CAPTURE')=='1'


def settings():
    cipher = Fernet(private_file('PASTPAPER_MAIL_KEY_FILE'))
    sender = normalize_email(os.environ['PASTPAPER_MAIL_FROM'])
    if capturing():
        spool = Path(os.environ['PASTPAPER_TEST_MAIL_DIR']).resolve(strict=True)
        if not spool.is_dir() or spool.stat().st_mode & 0o077 or not sender.endswith('@example.test'):
            raise ValueError('Local mail capture requires a private directory and a synthetic sender')
    else:
        host = os.environ['PASTPAPER_SMTP_HOST']
        if not host or not os.environ['PASTPAPER_SMTP_USER'] or not private_file('PASTPAPER_SMTP_PASSWORD_FILE'):
            raise ValueError('Authenticated SMTP is required')
    return cipher, sender


def enqueue(conn, to, title, message, delay=0, membership=(None,None)):
    cipher, sender = settings()
    if capturing() and not to.endswith('@example.test'):
        raise ValueError('The local test mailer only accepts synthetic recipients')
    mail = EmailMessage()
    mail['From'], mail['To'], mail['Subject'] = sender, normalize_email(to), title
    identity = uuid.uuid4().hex
    mail['Message-ID'] = f'<{identity}@{sender.rsplit("@", 1)[1]}>'
    mail.set_content(message)
    now = int(time.time())
    conn.execute('INSERT INTO public_outbox VALUES(?,?,\'queued\',0,?,?,?,?)',
                 (identity, cipher.encrypt(mail.as_bytes()), now + delay, now, *membership))


def assignment(conn, room, title, opens):
    if not public_mode.ORIGIN:
        return
    targets = conn.execute("""SELECT e.email,m.user_id FROM class_memberships m JOIN account_emails e ON e.user_id=m.user_id
        JOIN public_verified v ON v.user_id=e.user_id AND v.email=e.email LEFT JOIN account_access a ON a.user_id=m.user_id
        WHERE m.class_id=? AND m.status='active' AND COALESCE(a.enabled,1)=1""", (room,)).fetchall()
    for target in targets:
        enqueue(conn, target['email'], 'New PastPaper Studio assignment',
                f'{title}\n\nSign in to view the assignment: {public_mode.ORIGIN}/',
                delay=max(0, opens - int(time.time())), membership=(room,target['user_id']))


def recover(conn):
    # SMTP cannot confirm whether a process died after the server accepted a message.
    conn.execute("UPDATE public_outbox SET state='uncertain',payload=NULL WHERE state='sending'")


def deliver(connect):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        conn.execute("DELETE FROM public_outbox WHERE state NOT IN ('queued','sending') AND created<?", (now - 7*86400,))
        row = conn.execute("""SELECT * FROM public_outbox WHERE state='queued' AND scheduled<=?
                           ORDER BY scheduled,id LIMIT 1""", (now,)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE public_outbox SET state='sending',tries=tries+1 WHERE id=?", (row['id'],))
    state = 'failed'
    try:
        cipher, sender = settings()
        data = cipher.decrypt(row['payload'])
        message = BytesParser(policy=policy.SMTP).parsebytes(data)
        if row['assignment_class']:
            with connect() as conn:
                member = conn.execute('''SELECT 1 FROM class_memberships m JOIN classrooms c ON c.id=m.class_id
                    JOIN account_emails e ON e.user_id=m.user_id JOIN public_verified v ON v.user_id=e.user_id AND v.email=e.email
                    LEFT JOIN account_access a ON a.user_id=m.user_id
                    WHERE c.id=? AND c.archived=0 AND m.user_id=? AND m.status='active'
                      AND COALESCE(a.enabled,1)=1 AND e.email=?''',
                    (row['assignment_class'],row['student_id'],str(message['To']))).fetchone()
                if not member:
                    conn.execute("UPDATE public_outbox SET state='cancelled',payload=NULL WHERE id=?", (row['id'],))
                    return True
        if capturing():
            target = Path(os.environ['PASTPAPER_TEST_MAIL_DIR']) / f"{row['id']}.eml"
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
        else:
            context = ssl.create_default_context(cafile=certifi.where())
            with smtplib.SMTP_SSL(os.environ['PASTPAPER_SMTP_HOST'], 465, timeout=10, context=context) as smtp:
                smtp.login(os.environ['PASTPAPER_SMTP_USER'], private_file('PASTPAPER_SMTP_PASSWORD_FILE').decode())
                smtp.send_message(message, from_addr=sender, to_addrs=[str(message['To'])])
        state = 'accepted'
    except (smtplib.SMTPConnectError, smtplib.SMTPAuthenticationError, ConnectionRefusedError, FileNotFoundError):
        if row['tries'] < 2:
            state = 'queued'
    except (OSError, smtplib.SMTPException):
        state = 'uncertain'
    except Exception:
        LOG.error('Mail processing failed for queue entry %s', row['id'])
    with connect() as conn:
        conn.execute("""UPDATE public_outbox SET state=?, scheduled=?, payload=? WHERE id=?""",
                     (state, int(time.time()) + 60, row['payload'] if state == 'queued' else None, row['id']))
    return True
