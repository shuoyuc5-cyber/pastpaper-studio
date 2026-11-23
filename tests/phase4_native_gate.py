"""Focused, synthetic checks for the released document sandbox."""
import ctypes
import errno
import hashlib
import io
import json
import platform
import resource
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


def verify_archive(path):
    expected = {
        'pastpaper-web': 'ad0f1e4c9fcd76c1f948278a5c94156938708dede286f5b1bb5ef4a2bcc03818',
        'pastpaper-backend': '41d641b3d2395661a9c2f6cd76481989df9aebe9a62889f05348e461824aa16a',
    }
    with tarfile.open(path) as archive:
        manifests = json.load(archive.extractfile('index.json'))['manifests']
        for image, digest in expected.items():
            for tag in ('8c8b9730b8eb', '8c8b9730b8eb-amd64'):
                name = f'docker.io/library/{image}:{tag}'
                matches = [descriptor for descriptor in manifests
                           if descriptor.get('annotations', {}).get('io.containerd.image.name') == name]
                assert len(matches) == 1, name
                assert matches[0]['platform'] == {'os': 'linux', 'architecture': 'amd64'}, name
                assert matches[0]['digest'] == f'sha256:{digest}', name
            with archive.extractfile(f'blobs/sha256/{digest}') as manifest:
                assert hashlib.file_digest(manifest, 'sha256').hexdigest() == digest
            print(f'PASS {image} linux/amd64 manifest sha256:{digest}')


def landlock_abi():
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(444, None, 0, 1)
    return result, ctypes.get_errno() if result < 0 else 0


def docx(xml):
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', xml)
    return buffer.getvalue()


def deny_landlock_for_this_process():
    seccomp = ctypes.CDLL('libseccomp.so.2')
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7fff0000)
    assert context
    try:
        assert seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, 444, 0) == 0
        assert seccomp.seccomp_load(context) == 0
    finally:
        seccomp.seccomp_release(context)
    assert landlock_abi() == (-1, errno.EPERM)


def check_admission_and_watchdog(classwork, sandbox):
    entered = threading.Barrier(3, timeout=5)
    release = threading.Event()

    def hold(_op, _kind, *, payload, timeout):
        assert payload == b'fixture' and timeout == 35
        entered.wait()
        assert release.wait(5)
        return []

    with patch.object(sandbox, 'run', hold), ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(classwork.extract_document, b'fixture', 'docx') for _ in range(2)]
        try:
            entered.wait()
            expect_rejection(classwork, b'fixture', 429)
        finally:
            release.set()
        assert all(job.result() == [] for job in jobs)
    print('PASS two simultaneous classroom parsers, third rejected, 35 s production timeout')

    # A sleeping child makes the kill and reap path deterministic without an expensive payload.
    start = subprocess.Popen
    children = []

    def sleeping_process(_command, **options):
        child = start([sys.executable, '-c', 'import time; time.sleep(10)'], **options)
        children.append(child)
        return child

    with patch.object(sandbox.subprocess, 'Popen', sleeping_process):
        try:
            sandbox.run('class-import', 'docx', payload=b'fixture', timeout=0.25)
        except sandbox.SandboxFailure as error:
            assert str(error) == 'Document processing timed out'
        else:
            raise AssertionError('Sandbox watchdog accepted a stalled job')
    assert children[0].returncode == -signal.SIGKILL
    print('PASS watchdog killed and reaped an inert child')


def expect_rejection(classwork, data, status=422):
    try:
        classwork.extract_document(data, 'docx')
    except classwork.ClassroomError as error:
        assert error.status_code == status, error
    else:
        raise AssertionError(f'Expected classroom import rejection {status}')


def check_release():
    import pyexpat
    import pymupdf
    from app import classwork, pdf_sandbox, public_mode, security

    assert public_mode.ORIGIN
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    assert status['Uid'].split()[0] == '10001'
    assert int(status['CapEff'], 16) == int(status['CapBnd'], 16) == 0
    assert int(status['NoNewPrivs']) == 1 and int(status['Seccomp']) == 2
    Path('/etc/passwd').read_bytes()
    with socket.socket():
        pass
    assert pdf_sandbox.run('probe', '/etc/passwd') == {'filesystem': True, 'network': True}
    print('PASS stock container seccomp permits Landlock; sandbox denies file and socket access')

    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:p><w:r><w:t>Calculate 2 + 3</w:t></w:r></w:p></w:document>')
    valid = docx(xml)
    assert 'Calculate 2 + 3' in classwork.extract_document(valid, 'docx')[0]['text']
    expect_rejection(classwork, docx('<!DOCTYPE a [<!ENTITY b "sample">]><a>&b;</a>'))
    expect_rejection(classwork, docx(' ' * 3_000_001))
    print('PASS public DOCX path with', pyexpat.EXPAT_VERSION, 'rejects DTDs and >3,000,000 XML bytes')

    for _ in range(8):
        security.rate_limit('native-gate-docx-fixture', 8)
    try:
        security.rate_limit('native-gate-docx-fixture', 8)
    except security.HTTPException as error:
        assert error.status_code == 429
    else:
        raise AssertionError('Expected ninth import to be rate limited')
    print('PASS classroom rate limiter, compressed upload limit', security.classroom_upload_limit())

    with pymupdf.open() as source, pymupdf.open() as raster:
        page = source.new_page(width=430, height=300)
        page.insert_text((38, 38), 'Calculate 2 + 3', fontsize=22)
        for n, text in enumerate(('数学练习题', '请计算下列各题', '第一题：二加三等于几？')):
            page.insert_text((38, 92 + 46 * n), text, fontname='china-s', fontsize=24)
        target = raster.new_page(width=430, height=300)
        target.insert_image(target.rect, stream=page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes('png'))
        pdf = raster.tobytes()
    recognized = ' '.join(row['text'] for row in classwork.extract_document(pdf, 'pdf'))
    assert 'Calculate 2 + 3' in recognized and '计算下列' in ''.join(recognized.split()), recognized
    print('PASS sandboxed English and Simplified Chinese OCR from an image-only PDF')

    with tempfile.TemporaryDirectory() as job:
        result = subprocess.check_output([sys.executable, '-c', '''
import json, resource, sys
from pathlib import Path
from app.pdf_sandbox import constrain
constrain(Path(sys.argv[1]), ())
names = ('AS', 'CPU', 'FSIZE', 'CORE')
print(json.dumps({name: resource.getrlimit(getattr(resource, 'RLIMIT_' + name)) for name in names}))
''', job], text=True)
    limits = json.loads(result)
    assert limits == {'AS': [768 * 1024**2] * 2, 'CPU': [180, 185], 'FSIZE': [64 * 1024**2] * 2, 'CORE': [0, 0]}
    print('PASS actual sandbox process rlimits', json.dumps(limits))

    check_admission_and_watchdog(classwork, pdf_sandbox)
    deny_landlock_for_this_process()
    expect_rejection(classwork, valid)
    print('PASS valid DOCX rejected when Landlock is denied by an additional per-process seccomp filter')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--archive':
        verify_archive(sys.argv[2])
        raise SystemExit
    machine = platform.machine()
    print(f'Kernel={platform.release()} architecture={machine}', flush=True)
    assert sys.platform == 'linux' and machine in {'x86_64', 'aarch64'}
    abi, number = landlock_abi()
    print(f'Landlock ABI={abi} errno={number}', flush=True)
    assert abi >= 3
    if '--host' not in sys.argv:
        check_release()
