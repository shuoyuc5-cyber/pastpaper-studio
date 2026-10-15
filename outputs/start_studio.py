"""Start the installed local app independently of a Codex command session."""
from pathlib import Path
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
RUNTIME = ROOT / "work" / "runtime"
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")


def opener():
    handlers = [urllib.request.ProxyHandler({})]
    if (TLS / 'ca.pem').exists():
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(TLS / 'ca.pem'))))
    return urllib.request.build_opener(*handlers)


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ready(url, marker):
    try:
        with opener().open(url, timeout=2) as response:
            return marker in response.read().decode("utf-8")
    except (OSError, ValueError):
        return False


def check_frontend():
    base = "http://127.0.0.1:3000"
    with opener().open(base, timeout=5) as response:
        html = response.read().decode("utf-8")
        if response.headers.get('X-PastPaper-Transport') != 'lan-http':
            raise RuntimeError('当前端口不是新版局域网服务，请重新启动。')
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


def main():
    python = ROOT / "backend" / ".venv" / "bin" / "python"
    npm = shutil.which("npm")
    if not python.exists() or not npm or not (ROOT / "frontend" / ".next" / "BUILD_ID").exists():
        raise RuntimeError("缺少运行环境或网页构建，请按照项目 README 完成安装和构建。")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if '--restart' not in sys.argv and listening(8000):
        raise RuntimeError('请使用双击启动文件或 --restart，以确保后端载入新版局域网防护。')
    hosts = lan_hosts()
    (RUNTIME / 'lan-hosts.json').write_text(json.dumps(hosts))
    if '--restart' in sys.argv:
        for name, url, marker in [('backend','http://127.0.0.1:8000/api/health','PastPaper Studio API'),('frontend','https://127.0.0.1:3443/','PastPaper Studio')]:
            pid_path=RUNTIME / (name + '.pid')
            matches=ready(url,marker) or (name=='frontend' and ready('http://127.0.0.1:3000/','PastPaper Studio'))
            if pid_path.exists() and matches:
                pid=int(pid_path.read_text())
                try:
                    if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGTERM)
                except ProcessLookupError:pass
                except PermissionError as error:
                    raise RuntimeError('当前环境没有停止旧服务的权限，请在 Mac 终端运行启动文件完成切换。') from error
        deadline=time.monotonic()+8
        while any(listening(p) for p in (3000,3443,8000)) and time.monotonic()<deadline:time.sleep(.2)
        if any(listening(p) for p in (3000,3443,8000)):
            raise RuntimeError("旧服务尚未关闭，未启动新版本。请查看启动日志或关闭旧服务后重试。")
    services = [
        ("backend", 8000, "http://127.0.0.1:8000/api/health", "PastPaper Studio API",
         [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log", "--no-proxy-headers"]),
        ("frontend", 3000, "http://127.0.0.1:3000/", "PastPaper Studio", [npm, "run", "start"]),
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
    check_frontend()
    print("PastPaper Studio 已启动（局域网，无需证书）：http://localhost:3000/", flush=True)
    for host in hosts:
        if host.endswith('.local'):
            print(f'朋友网址（同一局域网，无需证书）：http://{host}:3000/', flush=True)
        elif '.' in host and host != '127.0.0.1':
            print(f'局域网 IP 网址：http://{host}:3000/', flush=True)
    print('HTTP 未加密，请使用可信局域网及独立密码；不要开放公网端口。', flush=True)
    print("可以关闭此窗口，网页服务会继续运行。Mac 重启后请再次双击启动。", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open("http://localhost:3000/")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"启动未完成：{error}", file=sys.stderr, flush=True)
        sys.exit(1)
