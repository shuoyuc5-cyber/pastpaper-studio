"""Start the installed local app independently of a Codex command session."""
from pathlib import Path
import argparse
import errno
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import re
import ssl
from https_setup import lan_hosts, TLS
import json

ROOT = Path(__file__).resolve().parent.parent
INSTALL_ROOT = Path(os.environ.get("PASTPAPER_INSTALL_ROOT", ROOT)).resolve()
RUNTIME = INSTALL_ROOT / "work" / "runtime"
WEB_PORT = int(os.environ.get("PASTPAPER_WEB_PORT", "3000"))
API_PORT = int(os.environ.get("PASTPAPER_BACKEND_PORT", "8000"))
if len({WEB_PORT, API_PORT, 3443}) != 3 or not all(1024 <= port <= 65535 for port in (WEB_PORT, API_PORT)):
    raise ValueError("Invalid Host ports")
BASE_URL = f"http://127.0.0.1:{WEB_PORT}"
API_HEALTH = f"http://127.0.0.1:{API_PORT}/api/health"
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")


def opener():
    handlers = [urllib.request.ProxyHandler({})]
    if (TLS / 'ca.pem').exists():
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(TLS / 'ca.pem'))))
    return urllib.request.build_opener(*handlers)


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        result=sock.connect_ex(("127.0.0.1", port))
        if result in (errno.EPERM,errno.EACCES):
            raise RuntimeError('当前环境无法检查本机端口。请在 Mac 终端运行启动文件。')
        return result == 0


def ready(url, marker):
    try:
        with opener().open(url, timeout=2) as response:
            return marker in response.read().decode("utf-8")
    except (OSError, ValueError):
        return False


def check_frontend(lan):
    base = BASE_URL
    with opener().open(base, timeout=5) as response:
        html = response.read().decode("utf-8")
        expected = 'lan-http' if lan else 'local-http'
        if response.headers.get('X-PastPaper-Transport') != expected:
            raise RuntimeError('网页正在以其他访问模式运行。请使用 --restart 切换模式。')
        if response.headers.get('X-PastPaper-Release') != release_name():
            raise RuntimeError('主机仍在运行其他版本。请使用 --restart 载入更新后的版本。')
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    if not scripts:
        raise RuntimeError("网页未返回启动脚本，请重新启动应用。")
    for src in scripts:
        if src.startswith('/_next/static/'):
            try:
                with opener().open(base + src, timeout=5) as response:
                    if 'javascript' not in response.headers.get('Content-Type', ''):
                        raise ValueError('不是 JavaScript 文件')
            except (OSError, ValueError) as error:
                raise RuntimeError("网页脚本版本不一致，请双击启动文件重启应用。") from error


def snapshot_frontend():
    source = ROOT / "frontend" / ".next"
    destination = ROOT / "frontend" / ".studio-runtime"
    if (destination / 'BUILD_ID').exists() and (destination / 'BUILD_ID').read_text() == (source / 'BUILD_ID').read_text():
        return
    temporary = destination.with_name(destination.name + '.tmp')
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(source, temporary, ignore=shutil.ignore_patterns('cache'))
    if destination.exists():
        shutil.rmtree(destination)
    temporary.rename(destination)


def release_name():
    return ROOT.name if INSTALL_ROOT != ROOT else 'v3'


def stop_services():
    groups = []
    legacy_tls_ports = (3443,) if WEB_PORT == 3000 else ()
    for name, port, urls, marker in (
        ('frontend', WEB_PORT, [BASE_URL + '/'] + ['https://127.0.0.1:3443/' for _ in legacy_tls_ports], 'PastPaper Studio'),
        ('backend', API_PORT, [API_HEALTH], 'PastPaper Studio API'),
    ):
        pid_path = RUNTIME / (name + '.pid')
        ports = (port, *legacy_tls_ports) if name == 'frontend' else (port,)
        if not any(listening(checked_port) for checked_port in ports):
            continue
        if not pid_path.exists() or not any(ready(url, marker) for url in urls):
            raise RuntimeError('端口仍被其他程序占用。请检查启动日志和端口归属。')
        pid = int(pid_path.read_text())
        try:
            listeners = set()
            for checked_port in ports:
                result = subprocess.run(['/usr/sbin/lsof', '-nP', '-tiTCP:' + str(checked_port), '-sTCP:LISTEN'],
                                        capture_output=True, text=True, timeout=3)
                listeners.update(int(value) for value in result.stdout.split() if value.isdecimal())
            if os.getpgid(pid) != pid or not listeners or not all(os.getpgid(child) == pid for child in listeners):
                raise RuntimeError('无法确认占用端口的进程属于此安装。')
            os.killpg(pid, 0)
            groups.append(pid)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise RuntimeError('当前环境没有停止服务的权限，请在 Mac 终端运行此命令。') from error
    for pid in groups:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 8
    while any(listening(p) for p in (WEB_PORT, API_PORT, *legacy_tls_ports)) and time.monotonic() < deadline:
        time.sleep(.2)
    if any(listening(p) for p in (WEB_PORT, API_PORT, *legacy_tls_ports)):
        raise RuntimeError('仍有服务占用端口。请检查启动日志和端口归属。')
    for name in ('frontend', 'backend'):
        (RUNTIME / (name + '.pid')).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='PastPaper Studio host launcher')
    operation = parser.add_mutually_exclusive_group()
    for flag in ('status', 'stop', 'restart'):
        operation.add_argument('--' + flag, action='store_true')
    parser.add_argument('--lan', action='store_true', help='explicitly allow devices on the local network')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    local_url = f'http://localhost:{WEB_PORT}/'
    if args.status:
        frontend = ready(BASE_URL + '/', 'PastPaper Studio')
        backend = ready(API_HEALTH, 'PastPaper Studio API')
        print(f'网页端口 {WEB_PORT}：{"运行中" if frontend else "未就绪"} · 后端端口 {API_PORT}：{"运行中" if backend else "未就绪"}')
        if frontend:
            print(local_url)
            with opener().open(BASE_URL + '/', timeout=3) as response:
                print('主机版本：' + (response.headers.get('X-PastPaper-Release') or '旧版'))
        return
    if args.stop:
        stop_services()
        print('PastPaper Studio 已停止。')
        return
    release_python = ROOT / "backend" / ".venv" / "bin" / "python"
    release_manifest = ROOT / 'release-manifest.json'
    if release_manifest.exists():
        expected = json.loads(release_manifest.read_text())
        installed = subprocess.check_output([str(release_python), '-c',
            'import certifi,sys; print(sys.version.split()[0]); print(certifi.__version__)'], text=True).splitlines()
        if installed != [expected['python'], expected['certifi']]:
            raise RuntimeError('此版本的 Python 环境与发布记录不匹配。')
    python = release_python if release_python.exists() else INSTALL_ROOT / "backend" / ".venv" / "bin" / "python"
    npm = shutil.which("npm")
    if not python.exists() or not npm or not (ROOT / "frontend" / ".next" / "BUILD_ID").exists():
        raise RuntimeError("缺少运行环境或网页构建，请按照项目 README 完成安装和构建。")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if args.restart:
        stop_services()
    if listening(WEB_PORT):
        check_frontend(args.lan)
    hosts = lan_hosts() if args.lan else ['localhost', '127.0.0.1']
    (RUNTIME / 'lan-hosts.json').write_text(json.dumps(hosts))
    services = [
        ("backend", API_PORT, API_HEALTH, "PastPaper Studio API",
         [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT), "--no-access-log", "--no-proxy-headers"]),
        ("frontend", WEB_PORT, BASE_URL + "/", "PastPaper Studio", [npm, "run", "start"]),
    ]
    for name, port, url, marker, command in services:
        if listening(port):
            if not ready(url, marker):
                raise RuntimeError(f"端口 {port} 正被其他服务使用，请先关闭该服务。")
            continue
        with (RUNTIME / f"{name}.log").open("ab") as log:
            environment = os.environ.copy()
            environment['PASTPAPER_REQUIRE_HTTPS'] = '0'
            environment['PASTPAPER_LAN_ONLY'] = '1'
            environment['PASTPAPER_HOST_LAN'] = '1' if args.lan else '0'
            environment['PASTPAPER_RUNTIME_DIR'] = str(RUNTIME)
            environment['PASTPAPER_RELEASE'] = release_name()
            if INSTALL_ROOT != ROOT:
                environment['PASTPAPER_DATA_DIR'] = str(INSTALL_ROOT / 'backend' / 'data')
            if name == 'frontend':
                snapshot_frontend()
                environment['PASTPAPER_DIST_DIR'] = '.studio-runtime'
            process = subprocess.Popen(
                command, cwd=ROOT / name, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True, env=environment,
            )
        deadline = time.monotonic() + 25
        while not ready(url, marker):
            if process.poll() is not None or time.monotonic() >= deadline:
                if process.poll() is None:
                    process.terminate()
                raise RuntimeError(f"{name} 启动失败，详情见 {RUNTIME / (name + '.log')}")
            time.sleep(0.5)
        (RUNTIME / f"{name}.pid").write_text(str(process.pid))
    check_frontend(args.lan)
    print(f"PastPaper Studio 已启动：{local_url}", flush=True)
    for host in hosts if args.lan else []:
        if host.endswith('.local'):
            print(f'朋友网址（同一局域网，无需证书）：http://{host}:{WEB_PORT}/', flush=True)
        elif '.' in host and host != '127.0.0.1':
            print(f'局域网 IP 网址：http://{host}:{WEB_PORT}/', flush=True)
    if args.lan:
        print('HTTP 未加密，请使用可信局域网及独立密码；不要开放公网端口。', flush=True)
    print("可以关闭此窗口，网页服务会继续运行。Mac 重启后请再次双击启动。", flush=True)
    if not args.no_browser:
        webbrowser.open(local_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"启动未完成：{error}", file=sys.stderr, flush=True)
        sys.exit(1)
