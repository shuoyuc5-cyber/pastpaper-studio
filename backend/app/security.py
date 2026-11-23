"""Bounded request handling and browser checks for the LAN app."""
import ipaddress
import socket
import shutil
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from . import public_mode

ATTEMPTS={}
LOCK=threading.Lock()
UPLOAD_LOCK=threading.Lock()
HEAVY_SLOTS=threading.BoundedSemaphore(2)
SINGLE_RANGE = re.compile(r'bytes=(?:[0-9]{1,20}-[0-9]{0,20}|-[0-9]{1,20})')
PDF_SIGNATURE = re.compile(rb'%PDF-[0-9]\.[0-9](?:\r\n?|\n)')

def check_pdf_header(data):
    if not PDF_SIGNATURE.match(data):
        raise ValueError('Invalid PDF signature')

@contextmanager
def heavy_operation(*, wait=0):
    if not HEAVY_SLOTS.acquire(timeout=wait):
        raise HTTPException(429, 'PDF processing is busy. Please try again shortly.')
    try:
        yield
    finally:
        HEAVY_SLOTS.release()

def check_range(request):
    values=request.headers.getlist('range')
    if values and (len(values)!=1 or not SINGLE_RANGE.fullmatch(values[0])):
        raise HTTPException(416, 'Only a single byte range is supported.')

def classroom_upload_limit():
    try:
        megabytes=int(os.environ.get('PASTPAPER_CLASSROOM_UPLOAD_MB','12'))
    except ValueError:
        megabytes=12
    return min(20,max(1,megabytes))*1024*1024

def store_upload(folder,path,data,u):
    with UPLOAD_LOCK:
        relative=path.relative_to(folder)
        current=folder
        for part in relative.parts[:-1]:
            if current.is_symlink():raise HTTPException(400,'文件路径无效')
            current=current/part
        if current.is_symlink():raise HTTPException(400,'文件路径无效')
        folder.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():raise HTTPException(400,'文件路径无效')
        if path.exists():
            if not path.is_file() or path.read_bytes()!=data:raise HTTPException(409,'同名文件内容不同，原文件不会被覆盖')
            return
        if public_mode.ORIGIN and shutil.disk_usage(folder).free < len(data) + 256*1024**2:
            raise HTTPException(507,'The file store has reached its safety reserve.')
        files=[p for p in folder.rglob('*') if p.is_file()]
        quota=(8 if u['role']=='admin' else 1)*1024**3
        if len(files)>=2000 or sum(p.stat().st_size for p in files)+len(data)>quota:
            raise HTTPException(413,'该账号的本机存储额度已用完，请联系管理员整理资料')
        temporary=folder/('.upload-'+secrets.token_hex(16))
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            with temporary.open('xb') as out:out.write(data)
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

def rate_limit(key,maximum,window=60):
    now=time.monotonic()
    with LOCK:
        if key not in ATTEMPTS and len(ATTEMPTS)>=2048:
            for old, (timestamps, lifetime) in list(ATTEMPTS.items()):
                if not timestamps or timestamps[-1]<=now-lifetime:
                    ATTEMPTS.pop(old)
            if len(ATTEMPTS)>=2048:raise HTTPException(429,'请求过于频繁，请稍后重试')
        attempts,_=ATTEMPTS.setdefault(key,([],window))
        attempts[:]=[t for t in attempts if t>now-window]
        if len(attempts)>=maximum:raise HTTPException(429,'请求过于频繁，请一分钟后重试')
        attempts.append(now)

def request_host(request):
    peer=request.client.host if request.client else ''
    forwarded=request.headers.get('x-forwarded-host') if peer in ('127.0.0.1','::1') else None
    return forwarded or request.headers.get('host','')

def client_peer(request):
    peer=request.client.host if request.client else ''
    if peer in ('127.0.0.1','::1'):
        peer=request.headers.get('x-forwarded-for',peer)
    try:
        address=ipaddress.ip_address(peer)
        return str(getattr(address,'ipv4_mapped',None) or address)
    except ValueError:
        return 'unknown'

def https_request(request):
    peer=request.client.host if request.client else ''
    return request.url.scheme=='https' or (peer in ('127.0.0.1','::1') and request.headers.get('x-forwarded-proto')=='https')

def own_device(request):
    """The production proxies replace forwarded headers with socket metadata."""
    if public_mode.ORIGIN:
        return False
    peer=request.client.host if request.client else ''
    hostname=urlparse('//'+request_host(request)).hostname
    if peer=='testclient':return hostname=='testserver'
    try:
        address=ipaddress.ip_address(peer)
        if not address.is_loopback:return False
        forwarded=ipaddress.ip_address(request.headers.get('x-forwarded-for',peer))
        if isinstance(forwarded,ipaddress.IPv6Address) and forwarded.ipv4_mapped:forwarded=forwarded.ipv4_mapped
        return forwarded.is_loopback and hostname in ('localhost','127.0.0.1','::1')
    except ValueError:return False

def browser_error(request):
    if public_mode.ORIGIN:
        if request.client is None or request.client.host not in ('127.0.0.1', '::1'):
            return 'Invalid application gateway.'
        if request.url.path == '/api/health' and not request.headers.get('x-forwarded-host'):
            return None
        if not https_request(request) or 'https://' + request_host(request).lower() != public_mode.ORIGIN:
            return 'Use the configured HTTPS site address.'
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != public_mode.ORIGIN:
            return 'This operation requires the configured site origin.'
        return None
    if os.environ.get('PASTPAPER_LAN_ONLY')=='1':
        try:
            address=ipaddress.ip_address(client_peer(request))
            if not (address.is_private or address.is_loopback or address.is_link_local):return '仅允许本机和局域网访问'
        except ValueError:return '访问来源无效'
    if os.environ.get('PASTPAPER_REQUIRE_HTTPS')=='1' and request.url.path!='/api/health' and not https_request(request):
        return '请使用 HTTPS 加密地址登录和操作'
    host=request_host(request)
    try:
        name=urlparse('//'+host).hostname or ''
        local=socket.gethostname().lower().removesuffix('.local')
        allowed=name.lower() in ('localhost',local,local+'.local')
        if request.client and request.client.host=='testclient' and name=='testserver':allowed=True
        try:
            ip=ipaddress.ip_address(name)
            allowed=ip.is_loopback or ip.is_private or ip.is_link_local
        except ValueError:pass
        if not allowed:return '请通过本机或局域网地址访问网站'
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('sec-fetch-site') in ('cross-site','same-site'):return '请从本站页面发起操作'
            origin=request.headers.get('origin')
            if origin and (urlparse(origin).scheme!=('https' if https_request(request) else 'http') or urlparse(origin).netloc.lower()!=host.lower()):return '请求来源与网站地址不匹配'
    except ValueError:return '请求地址无效'
    return None

class BodyLimit:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not scope['path'].startswith('/api/'):return await self.app(scope,receive,send)
        path=scope['path']
        limit=40*1024*1024 if path=='/api/import/upload' or (public_mode.ORIGIN and path.startswith('/api/import/') and path.endswith('/replace')) else 15*1024*1024 if path=='/api/attachments' else 256*1024
        if path.startswith('/api/classroom/classes/') and path.endswith('/document-import'):
            limit=classroom_upload_limit()
        try:length=int(dict(scope['headers']).get(b'content-length',b'0'))
        except ValueError:length=-1
        detail='Request exceeds the size limit.' if dict(scope['headers']).get(b'x-studio-language')==b'en' else '请求内容超过大小限制'
        if length<0 or length>limit:return await JSONResponse({'detail':detail},status_code=413)(scope,receive,send)
        size=0
        async def bounded_receive():
            nonlocal size
            message=await receive()
            if message['type']=='http.request':
                size+=len(message.get('body',b''))
                if size>limit:raise HTTPException(413,detail)
            return message
        await self.app(scope,bounded_receive,send)
