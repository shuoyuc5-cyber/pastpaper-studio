"""Run the production Next build, public FastAPI profile and worker with synthetic data."""
import argparse
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta, timezone
import base64
import ipaddress
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import httpx

ROOT = Path(__file__).resolve().parents[1]
ADMIN_EMAIL = 'operator@example.test'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def config(root):
    web, api = free_port(), free_port()
    while web == api:
        api = free_port()
    origin = f'https://127.0.0.1:{web}'
    data = root / 'data'
    data.mkdir(mode=0o700)
    mail = root / 'mail'
    mail.mkdir(mode=0o700)
    (data / '.pastpaper-public').write_text(origin)
    seed = secrets.token_bytes(20)
    files = {'MAIL_KEY_FILE': Fernet.generate_key(), 'ADMIN_TOTP_FILE': base64.b32encode(seed)}
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PastPaper Studio Local Sandbox')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=2))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .sign(key, hashes.SHA256()))
    files['TEST_TLS_CERT'] = cert.public_bytes(serialization.Encoding.PEM)
    files['TEST_TLS_KEY'] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption())
    env = {key: os.environ[key] for key in ('PATH','LANG','TMPDIR','CI') if key in os.environ}
    env.update(PASTPAPER_DATA_DIR=str(data), PASTPAPER_PUBLIC_ORIGIN=origin, PASTPAPER_PUBLIC_LOCAL='1',
               PASTPAPER_WEB_PORT=str(web), PASTPAPER_BACKEND_PORT=str(api), PASTPAPER_TEST_MAIL_DIR=str(mail),
               PASTPAPER_MAIL_FROM='no-reply@example.test', PYTHONUNBUFFERED='1', NEXT_TELEMETRY_DISABLED='1',
               PASTPAPER_DIST_DIR='.next-fullstack')
    for label, value in files.items():
        secret = root / label
        secret.write_bytes(value)
        env['PASTPAPER_' + label] = str(secret)
    return env, seed


@contextmanager
def services(root, env, start_worker=True):
    commands = {
        'api': [sys.executable, '-m', 'uvicorn', '--app-dir', 'backend', 'app.main:app', '--host',
                '127.0.0.1', '--port', env['PASTPAPER_BACKEND_PORT'], '--no-proxy-headers', '--no-access-log', '--timeout-keep-alive', '15'],
        'web': ['node', 'frontend/server-public.cjs'],
    }
    if start_worker:
        worker_script = str(ROOT / 'scripts/public_service.py')
        commands['worker'] = [sys.executable, worker_script, 'pdf-worker']
        commands['mail'] = [sys.executable, worker_script, 'mail-worker']
    processes = {}
    try:
        for name, command in commands.items():
            with (root / (name + '.log')).open('ab') as log:
                processes[name] = subprocess.Popen(command, env=env, cwd=ROOT, stdin=subprocess.DEVNULL,
                                                    stdout=log, stderr=log, start_new_session=True)
            if name in ('api','web'):
                base = ('http://127.0.0.1:' + env['PASTPAPER_BACKEND_PORT'] if name == 'api' else
                        env['PASTPAPER_PUBLIC_ORIGIN'])
                tls = ssl.create_default_context(cafile=env['PASTPAPER_TEST_TLS_CERT']) if name == 'web' else True
                with httpx.Client(verify=tls, trust_env=False, timeout=1) as client:
                    for _ in range(120):
                        try:
                            if client.get(base + '/api/health').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        if processes[name].poll() is not None:
                            break
                        time.sleep(.25)
                    else:
                        raise RuntimeError(f'{name} did not start. Check {root}/{name}.log')
                    if processes[name].poll() is not None:
                        raise RuntimeError(f'{name} exited. Check {root}/{name}.log')
        yield processes
    finally:
        import signal
        for process in reversed(processes.values()):
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        for process in reversed(processes.values()):
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['serve', 'verify'])
    parser.add_argument('--evidence', type=Path, help='keep synthetic logs and data in a new directory')
    args = parser.parse_args()
    root = args.evidence.resolve() if args.evidence else Path(tempfile.mkdtemp(prefix='studio-fullstack-'))
    if args.evidence:
        root.mkdir(mode=0o700)
    print(f'Local test artifacts: {root}', flush=True)
    try:
        env, seed = config(root)
        with (ROOT / 'frontend/.fullstack-build-lock').open('a') as lock:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'frontend', env=env, check=True)
            bootstrap = [sys.executable, str(ROOT / 'scripts/public_service.py'), 'bootstrap', 'QA Operator', ADMIN_EMAIL]
            if args.action == 'verify':
                password = secrets.token_urlsafe(20)
                subprocess.run(bootstrap, input=password + '\n', text=True, env=env, check=True, capture_output=True)
                sys.path.insert(0, str(ROOT / 'tests'))
                from verify_fullstack import verify
                verify(root, env, seed, password)
            else:
                subprocess.run(bootstrap, env=env, check=True)
                print('Enroll your authenticator using the base32 seed in ' + env['PASTPAPER_ADMIN_TOTP_FILE'])
                with services(root, env):
                    print(env['PASTPAPER_PUBLIC_ORIGIN'], 'test certificate:', env['PASTPAPER_TEST_TLS_CERT'], flush=True)
                    while True:
                        time.sleep(1)
    finally:
        if not args.evidence:
            shutil.rmtree(root)


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        pass
