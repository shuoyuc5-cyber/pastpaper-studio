"""Run document decoders with a per-job filesystem and syscall policy on Linux."""
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import tempfile

BACKEND = Path(__file__).resolve().parents[1]
LINUX = sys.platform == 'linux'
MIB = 1024 * 1024


class SandboxFailure(ValueError):
    pass


class PageUnavailable(SandboxFailure):
    pass


class Ruleset(ctypes.Structure):
    _fields_ = [('handled_access_fs', ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]


def constrain(job, inputs):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64*MIB, 64*MIB))
    resource.setrlimit(resource.RLIMIT_CPU, (180, 185))
    if not LINUX:
        return
    resource.setrlimit(resource.RLIMIT_AS, (768*MIB, 768*MIB))
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise RuntimeError('PDF isolation requires a supported 64-bit Linux architecture')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    seccomp = ctypes.CDLL('libseccomp.so.2')
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError('Cannot set no_new_privs')
    abi = libc.syscall(444, None, 0, 1)
    if abi < 3:  # Landlock ABI 3 additionally controls truncation.
        raise RuntimeError('PDF isolation requires Linux Landlock ABI 3 or later')
    allow_file = (1 << 2)
    allow_runtime = allow_file | (1 << 0) | (1 << 3)
    handled = (1 << 15) - 1
    ruleset = Ruleset(handled)
    fd = libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if fd < 0:
        raise RuntimeError('Unable to create PDF filesystem ruleset')
    try:
        def rule(path, access):
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                spec = PathRule(access, parent)
                if libc.syscall(445, fd, 1, ctypes.byref(spec), 0) != 0:
                    raise RuntimeError('Unable to install PDF filesystem rule')
            finally:
                os.close(parent)
        # Read, write, truncate, add and remove ordinary files and directories.
        rule(job, sum(1 << bit for bit in (1, 2, 3, 4, 5, 7, 8, 14)))
        for path in ('/usr', '/lib', '/lib64', '/etc/fonts', '/var/cache/fontconfig', '/etc/ld.so.cache', '/dev/null', '/dev/urandom'):
            if Path(path).exists():
                rule(path, allow_runtime if Path(path).is_dir() else allow_file | ((1 << 1) if path=='/dev/null' else 0))
        for path in set(inputs):
            rule(path, allow_file)
        if libc.syscall(446, fd, 0) != 0:
            raise RuntimeError('Unable to enforce PDF filesystem policy')
    finally:
        os.close(fd)

    context = seccomp.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError('Unable to create PDF syscall policy')
    try:
        for name in (b'socket', b'socketpair', b'connect', b'bind', b'listen', b'accept', b'accept4',
                     b'ptrace', b'process_vm_readv', b'process_vm_writev', b'pidfd_getfd', b'io_uring_setup', b'kill', b'tkill', b'tgkill', b'pidfd_send_signal'):
            number = seccomp.seccomp_syscall_resolve_name(name)
            if number >= 0 and seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0):
                raise RuntimeError('Unable to add PDF syscall rule')
        if seccomp.seccomp_load(context):
            raise RuntimeError('Unable to enforce PDF syscall policy')
    finally:
        seccomp.seccomp_release(context)


def run(op, *args, inputs=(), payload=None, binary=False, timeout=45, preserve_ocr=None):
    with tempfile.TemporaryDirectory(prefix='studio-pdf-') as directory:
        job = Path(directory).resolve()
        files = [str(Path(path).resolve(strict=True)) for path in inputs if path]
        if payload is not None:
            source = job / 'input'
            source.write_bytes(payload)
            args = (str(source), *args)
        script = [sys.executable, '-m', 'app.pdf_sandbox']
        env = {'PATH':os.defpath if LINUX else os.environ.get('PATH',os.defpath), 'TMPDIR':str(job),
               'PASTPAPER_DATA_DIR':str(job), 'OMP_THREAD_LIMIT':'1', 'PYTHONDONTWRITEBYTECODE':'1',
               'HOME':str(job), 'XDG_CACHE_HOME':str(job)}
        with (job/'result').open('w+b') as result:
            proc = subprocess.Popen(script, cwd=BACKEND, env=env, stdin=subprocess.PIPE,
                                    stdout=result, stderr=subprocess.DEVNULL, close_fds=True,
                                    start_new_session=True)
            try:
                proc.communicate(json.dumps([op, args, files]).encode(), timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise SandboxFailure('Document processing timed out') from exc
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if proc.returncode == 4:
                raise PageUnavailable('Requested PDF page is unavailable')
            if proc.returncode:
                raise SandboxFailure('Document processing was rejected or exceeded its isolation limits')
            result.seek(0)
            output = result.read()
        if preserve_ocr and not (job/'ocr').is_symlink():
            cache = Path(preserve_ocr)
            cache.mkdir(parents=True, exist_ok=True)
            for path in (job/'ocr').glob('*.json'):
                if path.is_file() and not path.is_symlink() and len(path.stem.split('-')[0])==64 and path.stat().st_size<=2*MIB:
                    # Keep sidecars available for the UI and backups. The parser never reads the shared cache.
                    with tempfile.NamedTemporaryFile(dir=cache,delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(path.read_bytes())
                    try:
                        temporary.replace(cache/path.name)
                    finally:
                        temporary.unlink(missing_ok=True)
        return output if binary else json.loads(output)


def render_page(path, number):
    import pymupdf
    from .render_limits import check_render_size
    with pymupdf.open(path) as doc:
        if not 1 <= number <= len(doc):
            raise IndexError('Page number out of range')
        page = doc[number-1]
        check_render_size(page.rect, 1.8)
        return page.get_pixmap(matrix=pymupdf.Matrix(1.8,1.8),alpha=False).tobytes('png')


def inspect_pdf(path, public=False):
    import pymupdf
    from .ocr import text_in
    from .security import check_pdf_header
    with Path(path).open('rb') as source:
        check_pdf_header(source.read(10))
    with pymupdf.open(path) as doc:
        if doc.is_encrypted:
            raise ValueError('PDF 已加密，无法读取')
        count = len(doc)
        if public and (not doc.is_pdf or not 1 <= count <= 200):
            raise ValueError('Public PDF imports must contain 1 to 200 pages.')
        return count, text_in(doc[0])[:5000] if count else '', (doc.metadata or {}).get('title') or ''


def image_png(path):
    import pymupdf
    data = path if isinstance(path,bytes) else Path(path).read_bytes()
    profile = pymupdf.image_profile(data)
    if not profile or profile['width']<=0 or profile['height']<=0 or profile['width']*profile['height']>30_000_000:
        raise ValueError('图片过大或格式无效')
    pix = pymupdf.Pixmap(data)
    if pix.width*pix.height>30_000_000:
        raise ValueError('图片过大')
    return pix.tobytes('png')


def segment_data(path, groups=None, plain=False):
    import pymupdf
    from .question_engine import segment_text, validate_segments
    if groups is not None:
        for segments in groups:
            validate_segments(path, segments)
    with pymupdf.open(path) as doc:
        if groups is None:
            segments = [{'page':i+1,'rect':list(page.rect)} for i,page in enumerate(doc)]
            return [segments, segment_text(doc, segments)]
        if plain:
            return ['\n'.join(doc[s['page']-1].get_text('text',clip=pymupdf.Rect(s['rect']),sort=True) for s in group)
                    for group in groups]
        return [segment_text(doc, group) for group in groups]


def probe(blocked):
    import socket
    try:
        Path(blocked).read_bytes()
    except PermissionError:
        filesystem = True
    else:
        filesystem = False
    try:
        with socket.socket():
            network = False
    except PermissionError:
        network = True
    return {'filesystem':filesystem,'network':network}


def main():
    import socket
    import pymupdf
    from . import ocr, render_limits, security
    from .class_import import extract, questions
    from .question_engine import crop_png, extract_questions
    from .pdf_export import assemble
    op,args,files = json.load(sys.stdin)
    methods = {'page':render_page,'crop':crop_png,'inspect':inspect_pdf,'index':extract_questions,
               'segments':segment_data, 'image':image_png,'class-import':lambda path,kind:questions(extract(Path(path),kind)),
               'export':assemble,'probe':probe}
    constrain(Path(os.environ['TMPDIR']),files)
    try:
        output = methods[op](*args)
    except IndexError:
        sys.exit(4)
    if isinstance(output,bytes):
        sys.stdout.buffer.write(output)
    else:
        json.dump(output,sys.stdout,ensure_ascii=False)


if __name__=='__main__':
    main()
