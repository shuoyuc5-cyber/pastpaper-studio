"""Email login identifiers and versioned password hashes."""
import hashlib
import hmac
import re
import secrets
from threading import BoundedSemaphore

EMAIL_LOCAL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}")
EMAIL_LABEL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?')
EMAIL_SUFFIX = re.compile(r'(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{2,59})', re.I)
HASH_SLOTS = BoundedSemaphore(2)
DUMMY_SALT = secrets.token_hex(16)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email)>254 or email.count('@')!=1:
        raise ValueError('Invalid email address')
    local, domain = email.split('@')
    labels = domain.split('.')
    if (not EMAIL_LOCAL.fullmatch(local) or local.startswith('.') or local.endswith('.') or '..' in local
            or len(labels)<2 or not all(EMAIL_LABEL.fullmatch(label) for label in labels)
            or not EMAIL_SUFFIX.fullmatch(labels[-1])):
        raise ValueError('Invalid email address')
    return email


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    with HASH_SLOTS:
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1,
                             dklen=32, maxmem=192*1024*1024)
    return f'scrypt-v1:{salt}:{key.hex()}'


def verify_password(password: str, stored: str | None) -> tuple[bool, str | None]:
    if not stored:
        password_hash(password, DUMMY_SALT)
        return False, None
    try:
        if stored.startswith('scrypt-v1:'):
            _, salt, _ = stored.split(':')
            return hmac.compare_digest(password_hash(password, salt), stored), None
        salt, digest = stored.split(':')
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
        if hmac.compare_digest(key, digest):
            return True, password_hash(password)
    except (ValueError, TypeError):
        pass
    return False, None
