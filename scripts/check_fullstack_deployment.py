"""Local, read-only check of the independent deployment templates."""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy/fullstack'
compose = yaml.safe_load((DEPLOY/'compose.staging.yml').read_text())
validation = compose['services']['verify']
assert validation['network_mode'] == 'none'
assert not validation.get('ports')
assert 'ALL' in validation['cap_drop']

edge = yaml.safe_load((DEPLOY/'cloudflared.example.yml').read_text())
ingress, fallback = edge['ingress']
access = ingress['originRequest']['access']
assert access['required'] is True and len(access['audTag'])==1
assert ingress['service']=='http://127.0.0.1:3000'
assert fallback=={'service':'http_status:404'}
platform = {path.stem.removeprefix('pastpaper-'):path.read_text() for path in (DEPLOY/'systemd').glob('*.service')}
assert set(platform)=={'mail','web','api','pdf'}
for contents in platform.values():
    assert re.search(r'^User=pastpaper$',contents,re.M)
    assert re.search(r'^NoNewPrivileges=yes$',contents,re.M)
    assert re.search(r'^MemoryMax=\d+M$',contents,re.M)
assert '--host 127.0.0.1' in platform['api'] and '--no-proxy-headers' in platform['api']
assert 'PrivateNetwork=yes' in platform['pdf'] and 'InaccessiblePaths=/etc/pastpaper/secrets' in platform['pdf']
assert 'InaccessiblePaths=/var/lib/pastpaper/data' in platform['web']
print('PASS deployment template invariants (Compose, Access, loopback, Linux service limits)')
