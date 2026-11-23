"""Probe disposable loopback HTTPS; never register accounts or read real credentials."""
import argparse
import http.client
import json
import ssl

parser = argparse.ArgumentParser()
parser.add_argument('--certificate', required=True)
parser.add_argument('--backend', type=int, default=39624)
parser.add_argument('--https', type=int, default=39625)
parser.add_argument('--redirect', type=int, default=39626)
args = parser.parse_args()
ports = (args.backend, args.https, args.redirect)
if len(set(ports)) != 3 or not all(39600 <= value <= 39699 for value in ports):
    parser.error('Use three distinct isolated fixture ports in 39600–39699.')

context = ssl.create_default_context(cafile=args.certificate)
host = '127.0.0.1'
origin = f'https://{host}:{args.https}'


def call(port, route, *, method='GET', data=None, headers=None, secure=False):
    conn = (http.client.HTTPSConnection(host,port,context=context,timeout=5) if secure
            else http.client.HTTPConnection(host,port,timeout=5))
    try:
        conn.request(method,route,body=data,headers=headers or {})
        response = conn.getresponse()
        return response.status, dict((k.lower(),v) for k,v in response.getheaders()), response.read()
    finally:
        conn.close()


health = call(args.https,'/api/health',secure=True)
assert health[0]==200 and health[1].get('x-pastpaper-transport')=='https'
assert json.loads(health[2])['service']=='PastPaper Studio API'
redirect = call(args.redirect,'/')
assert redirect[0]==302 and redirect[1]['location']==origin+'/'
assert call(args.redirect,'/api/auth/login',method='POST',headers={'X-Forwarded-Proto':'https'})[0]==426
assert call(args.backend,'/api/auth/me')[0]==403
assert call(args.https,'/api/auth/me',secure=True,headers={'Host':'malicious.example.test'})[0]==403

login_data = json.dumps({'email':'tls-admin@example.test','password':'fixture-password-no-secrets'})
headers = {'Content-Type':'application/json', 'Origin':origin}
assert call(args.https,'/api/auth/login',method='POST',data=login_data,secure=True,
            headers={**headers,'Origin':'https://malicious.example.test'})[0]==403
login = call(args.https,'/api/auth/login',method='POST',data=login_data,secure=True,headers=headers)
assert login[0]==200, 'Prepare the exact known synthetic account in the disposable TLS database.'
cookie = login[1].get('set-cookie','')
assert all(f'; {x}' in cookie.lower() for x in ('secure','httponly','samesite=strict'))
assert login[1].get('cache-control')=='private, no-store'
assert json.loads(call(args.https,'/api/auth/me',secure=True,headers={'Cookie':cookie.split(';',1)[0]})[2])['user']
print('PASS: actual HTTPS, HTTP redirect, origin and host rejection, secure login and session')
