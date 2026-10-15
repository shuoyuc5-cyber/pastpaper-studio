"""Bounded request handling and browser checks for the LAN app."""
import ipaddress
import socket
import os
import secrets
import threading
import time
from urllib.parse import urlparse
from fastapi import HTTPException
from fastapi.responses import JSONResponse

ATTEMPTS={}
LOCK=threading.Lock()
UPLOAD_LOCK=threading.Lock()

def store_upload(folder,path,data,u):
    with UPLOAD_LOCK:
        folder.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():raise HTTPException(400,'文件路径无效')
        if path.exists():
            if path.read_bytes()!=data:raise HTTPException(409,'同名文件内容不同，原文件不会被覆盖')
            return
        files=[p for p in folder.rglob('*') if p.is_file()]
        quota=(8 if u['role']=='admin' else 1)*1024**3
        if len(files)>=2000 or sum(p.stat().st_size for p in files)+len(data)>quota:
            raise HTTPException(413,'该账号的本机存储额度已用完，请联系管理员整理资料')
        temporary=folder/('.upload-'+secrets.token_hex(16))
        try:
            with temporary.open('xb') as out:out.write(data)
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

def rate_limit(key,maximum,window=60):
    now=time.monotonic()
    with LOCK:
        for old in list(ATTEMPTS):
            if not ATTEMPTS[old] or ATTEMPTS[old][-1]<=now-window:ATTEMPTS.pop(old,None)
        if key not in ATTEMPTS and len(ATTEMPTS)>=2048:raise HTTPException(429,'请求过于频繁，请稍后重试')
        attempts=ATTEMPTS.setdefault(key,[])
        attempts[:]=[t for t in attempts if t>now-window]
        if len(attempts)>=maximum:raise HTTPException(429,'请求过于频繁，请一分钟后重试')
        attempts.append(now)

def request_host(request):
    peer=request.client.host if request.client else ''
    forwarded=request.headers.get('x-forwarded-host') if peer in ('127.0.0.1','::1') else None
    return forwarded or request.headers.get('host','')

def https_request(request):
    peer=request.client.host if request.client else ''
    return request.url.scheme=='https' or (peer in ('127.0.0.1','::1') and request.headers.get('x-forwarded-proto')=='https')

def browser_error(request):
    if os.environ.get('PASTPAPER_LAN_ONLY')=='1':
        peer=request.client.host if request.client else ''
        if peer in ('127.0.0.1','::1'):
            peer=request.headers.get('x-forwarded-for',peer).strip()
        try:
            address=ipaddress.ip_address(peer)
            if address.version==6 and address.ipv4_mapped:address=address.ipv4_mapped
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
        limit=40*1024*1024 if path=='/api/import/upload' else 15*1024*1024 if path=='/api/attachments' else 256*1024
        try:length=int(dict(scope['headers']).get(b'content-length',b'0'))
        except ValueError:length=-1
        if length<0 or length>limit:return await JSONResponse({'detail':'请求内容超过大小限制'},status_code=413)(scope,receive,send)
        size=0
        async def bounded_receive():
            nonlocal size
            message=await receive()
            if message['type']=='http.request':
                size+=len(message.get('body',b''))
                if size>limit:raise HTTPException(413,'请求内容超过大小限制')
            return message
        await self.app(scope,bounded_receive,send)
