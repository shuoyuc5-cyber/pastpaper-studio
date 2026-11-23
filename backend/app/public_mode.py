"""Independent public profile. Importing this module never opens the LAN database."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

ORIGIN = os.getenv('PASTPAPER_PUBLIC_ORIGIN', '')
LOCAL = os.getenv('PASTPAPER_PUBLIC_LOCAL') == '1'
MARKER = '.pastpaper-public'
AUTH_ROUTES = {
    '/api/auth/public-register', '/api/auth/forgot-password', '/api/auth/complete-link',
}
# Each matching handler still checks user, file or classroom ownership.
STAFF_ROUTES = re.compile(
    r'/api/(?:import/|catalog/index$|papers/[^/]+/(?:sharing|layout-seed)$|layout/|questions/[^/]+(?:/split)?$)'
)
HOST_ONLY = {
    '/api/settings/source-folder', '/api/settings/select-folder', '/api/scan',
    '/api/auth/register',
}


def validate_data(data: Path):
    if not ORIGIN:
        return
    parsed = urlsplit(ORIGIN)
    if (parsed.scheme != 'https' or parsed.netloc != parsed.hostname and not LOCAL
            or parsed.path or parsed.query or parsed.fragment or parsed.username is not None
            or (LOCAL and (parsed.hostname != '127.0.0.1' or not parsed.port))
            or (not LOCAL and not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', parsed.hostname or ''))
            or (not LOCAL and parsed.hostname.split('.')[-1] in ('local', 'localhost', 'test', 'invalid'))
            or os.getenv('PASTPAPER_LAN_ONLY') == '1'
            or not os.getenv('PASTPAPER_DATA_DIR')
            or not (data / MARKER).is_file()
            or (data / MARKER).is_symlink()
            or (data / MARKER).read_text().strip() != ORIGIN):
        raise RuntimeError('Public profile requires its own explicitly initialized data directory and HTTPS origin')
