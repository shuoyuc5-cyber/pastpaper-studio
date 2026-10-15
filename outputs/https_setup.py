"""Create a local CA and renewable LAN certificate; never export private keys."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

ROOT = Path(__file__).resolve().parent.parent
TLS = ROOT / 'backend' / 'data' / 'tls'
PUBLIC = ROOT / 'outputs' / 'PastPaper Studio 局域网证书.cer'


def lan_hosts():
    hosts = {'localhost', '127.0.0.1', '::1'}
    name = socket.gethostname().lower().removesuffix('.local')
    hosts.update((name, name + '.local'))
    result = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True, check=True)
    for value in re.findall(r'\binet\s+(\d+\.\d+\.\d+\.\d+)', result.stdout):
        address = ipaddress.ip_address(value)
        if address.is_private and not address.is_loopback:
            hosts.add(value)
    return sorted(hosts)


def write_private(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as out:
        os.chmod(temporary, 0o600)
        out.write(data)
    os.replace(temporary, path)


def key_bytes(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def setup():
    TLS.mkdir(parents=True, exist_ok=True)
    os.chmod(TLS, 0o700)
    now = datetime.now(timezone.utc)
    ca_path, ca_key_path = TLS / 'ca.pem', TLS / 'ca-key.pem'
    if ca_path.exists() != ca_key_path.exists():
        raise RuntimeError('证书签发文件不完整，请保留现有文件并联系管理员修复。')
    if ca_path.exists():
        ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        if ca_key.public_key().public_numbers() != ca.public_key().public_numbers():
            raise RuntimeError('证书与签发私钥不匹配。')
        if ca.not_valid_after_utc < now + timedelta(days=10):
            raise RuntimeError('局域网根证书即将过期，需要更新并让设备重新信任证书。')
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PastPaper Studio Local CA')])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=730))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .sign(ca_key, hashes.SHA256()))
        write_private(ca_key_path, key_bytes(ca_key))
        write_private(ca_path, ca.public_bytes(serialization.Encoding.PEM))
    os.chmod(ca_key_path, 0o600)
    hosts = lan_hosts()
    names = []
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    cert_path, key_path = TLS / 'server.pem', TLS / 'server-key.pem'
    renew = True
    if cert_path.exists() and key_path.exists():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        renew = (cert.not_valid_after_utc < now + timedelta(days=10)
                 or cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value != x509.SubjectAlternativeName(names)
                 or cert.issuer != ca.subject
                 or cert.public_key().public_numbers() != key.public_key().public_numbers())
    if renew:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PastPaper Studio')]))
                .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(min(now + timedelta(days=90), ca.not_valid_after_utc))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName(names), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        write_private(key_path, key_bytes(key))
        write_private(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(key_path, 0o600)
    write_private(TLS / 'hosts.json', json.dumps(hosts).encode())
    PUBLIC.write_bytes(ca.public_bytes(serialization.Encoding.DER))
    fingerprint = ca.fingerprint(hashes.SHA256()).hex().upper()
    (ROOT / 'outputs' / '局域网证书指纹.txt').write_text('PastPaper Studio Local CA\nSHA-256: ' + fingerprint + '\n仅分享公开 .cer 文件，不分享私钥。\n', encoding='utf-8')
    print('公开证书：' + str(PUBLIC), flush=True)
    print('证书 SHA-256：' + fingerprint, flush=True)
    return hosts


def trust_on_mac():
    verified = subprocess.run(['/usr/bin/security', 'verify-cert', '-c', str(TLS / 'server.pem'), '-p', 'ssl', '-s', 'localhost'], capture_output=True)
    if verified.returncode == 0:
        return
    print('首次开启 HTTPS：Mac 将请求信任本网站的局域网证书，请在系统提示中确认。', flush=True)
    subprocess.run(['/usr/bin/security', 'add-trusted-cert', '-r', 'trustRoot', '-p', 'ssl',
                    '-k', str(Path.home() / 'Library' / 'Keychains' / 'login.keychain-db'), str(TLS / 'ca.pem')], check=True)
    subprocess.run(['/usr/bin/security', 'verify-cert', '-c', str(TLS / 'server.pem'), '-p', 'ssl', '-s', 'localhost'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--trust', action='store_true')
    args = parser.parse_args()
    setup()
    if args.trust:
        trust_on_mac()
