"""Provision the independent instance or run its single durable PDF/mail consumer."""
import argparse
import fcntl
from getpass import getpass
import logging
import subprocess
import time
import os
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app import main, studio, public_accounts, public_mail, public_mode

logger = logging.getLogger('pastpaper.worker')


def bootstrap(args):
    with main.connect() as conn:
        if conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise RuntimeError('Bootstrap is only for a fresh independent database.')
    password = getpass('Independent administrator password: ')
    public_accounts.validate_password(password)
    account = studio.AccountCredentials(username=args.username, email=args.email, password=password)
    encoded = studio.password_hash(password)
    with main.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise RuntimeError('Bootstrap is only for a fresh independent database.')
        user = studio.insert_account(conn, account, 'admin', encoded)
        conn.execute('INSERT INTO public_verified VALUES(?,?)', (user['id'], user['email']))
    print('Independent administrator created. Sign in using the separately enrolled authenticator.')


def next_pdf():
    with main.connect() as conn:
        source = conn.execute("""SELECT id,path FROM source_files
            WHERE status IN ('waiting','processing') ORDER BY added_at,id LIMIT 1""").fetchone()
        paper = conn.execute("""SELECT p.id, q.file_hash || ':' || COALESCE(m.file_hash,'') || ':' || ? AS wanted
            FROM papers p JOIN source_files q ON q.id=p.qp_file_id
            LEFT JOIN source_files m ON m.id=p.ms_file_id LEFT JOIN paper_index i ON i.paper_id=p.id
            WHERE q.status='completed' AND (m.id IS NULL OR m.status='completed')
              AND (i.signature IS NULL OR i.signature<>wanted)
            ORDER BY p.updated_at,p.id LIMIT 1""", (studio.INDEX_VERSION,)).fetchone()
    return source, paper


def process_pdf(command, value, stopped):
    child = subprocess.Popen([sys.executable, __file__, command, value],
                             stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 240
    while child.poll() is None:
        if stopped.wait(.2) or time.monotonic() >= deadline:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            break
    return child.returncode == 0


def worker(kind):
    lock_name = {'worker':'.all-worker-lock','pdf-worker':'.pdf-worker-lock','mail-worker':'.mail-worker-lock'}[kind]
    with (main.DATA_DIR / lock_name).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (main.DATA_DIR / '.public-worker-mode').open('a') as mode:
            fcntl.flock(mode, (fcntl.LOCK_EX if kind=='worker' else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            worker_loop(kind)


def worker_loop(kind):
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    mail_enabled = kind!='pdf-worker'
    pdf_enabled = kind!='mail-worker'
    if mail_enabled:
        with main.connect() as conn:
            public_mail.recover(conn)
    while not stopped.is_set():
        try:
            if mail_enabled:
                for _ in range(20):
                    if stopped.is_set() or not public_mail.deliver(main.connect):
                        break
            source, paper = next_pdf() if pdf_enabled else (None,None)
            if source and not stopped.is_set():
                ok = process_pdf('scan-one', source['id'], stopped)
                if not ok and not stopped.is_set():
                    with main.connect() as conn:
                        conn.execute("""UPDATE source_files SET status='failed',error=?,updated_at=?
                            WHERE id=? AND status IN ('waiting','processing')""",
                            ('PDF processing could not finish within its limits.', main.now_iso(), source['id']))
            if paper and not stopped.is_set():
                ok = process_pdf('index-one', paper['id'], stopped)
                if not ok and not stopped.is_set():
                    with main.connect() as conn:
                        conn.execute("""INSERT INTO paper_index VALUES(?,?,'failed',?,?)
                            ON CONFLICT(paper_id) DO UPDATE SET signature=excluded.signature,
                            status=excluded.status,error=excluded.error,updated_at=excluded.updated_at""",
                            (paper['id'], paper['wanted'], 'Question indexing was interrupted.', main.now_iso()))
            if not source and not paper:
                stopped.wait(2)
        except Exception:
            logger.error('Background cycle failed. Will retry.')
            stopped.wait(3)


def main_cli():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('bootstrap')
    setup.add_argument('username')
    setup.add_argument('email')
    for mode in ('worker','pdf-worker','mail-worker'):
        sub.add_parser(mode)
    sub.add_parser('scan-one').add_argument('id')
    sub.add_parser('index-one').add_argument('id')
    options = parser.parse_args()
    if not public_mode.ORIGIN:
        parser.error('An independent deployment profile is required')
    if options.command == 'scan-one':
        with main.connect() as conn:
            row = conn.execute("SELECT path,owner_id FROM source_files WHERE id=? AND status IN ('waiting','processing')",
                               (options.id,)).fetchone()
        if row:
            path = Path(row['path'])
            if not path.is_relative_to(main.DATA_DIR / 'uploads' / row['owner_id']):
                parser.error('Invalid queued path')
            main.scan_library(public_path=path)
        return
    if options.command == 'index-one':
        studio.index_catalog(options.id)
        return
    if options.command == 'bootstrap':
        public_accounts.totp_secret()
        public_mail.settings()
        main.init_db()
        bootstrap(options)
    else:
        if options.command!='pdf-worker':
            public_mail.settings()
        worker(options.command)


if __name__ == '__main__':
    main_cli()
