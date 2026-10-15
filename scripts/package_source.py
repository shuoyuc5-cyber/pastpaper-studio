"""Package an explicit source allowlist, never a running user's data directory."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FIXED=[
    '.gitignore','README.md','README.zh-CN.md','LICENSE','SECURITY.md',
    'CONTRIBUTING.md','THIRD_PARTY_NOTICES.md','backend/requirements.txt',
    'backend/requirements-lock.txt','frontend/package.json','frontend/package-lock.json',
    'frontend/tsconfig.json','frontend/next.config.ts','frontend/server-lan.cjs',
    'frontend/server-https.cjs','outputs/start_studio.py','outputs/https_setup.py',
    'outputs/Start PastPaper Studio.command','outputs/启动 PastPaper Studio.command',
    'scripts/package_source.py',
]
GROUPS={'backend/app':{'.py'},'backend/scripts':{'.py'},'frontend/app':{'.ts','.tsx','.css'},'docs':{'.md'}}


def source_files():
    paths=set(FIXED)
    for directory,suffixes in GROUPS.items():
        for path in (ROOT/directory).rglob('*'):
            if path.is_file() and path.suffix in suffixes and '__pycache__' not in path.parts:
                paths.add(path.relative_to(ROOT).as_posix())
    for name in sorted(paths):
        path=ROOT/name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f'Unsafe or missing source file: {name}')
        text=path.read_text(encoding='utf-8')
        if re.search(r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{30,}',text):
            raise ValueError(f'Possible credential in source: {name}')
        if str(Path.home())+'/' in text:
            raise ValueError(f'Personal machine reference in source: {name}')
        yield name,path


def main():
    files=list(source_files())
    destination=ROOT/'dist';destination.mkdir(exist_ok=True)
    archive=destination/'pastpaper-studio-source.zip'
    temporary=archive.with_suffix('.tmp')
    manifest=[{'path':name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for name,path in files]
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as out:
        for name,path in files:
            info=zipfile.ZipInfo('pastpaper-studio/'+name)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3
            info.external_attr=(0o100755 if name.endswith('.command') else 0o100644)<<16
            out.writestr(info,path.read_bytes())
        out.writestr('pastpaper-studio/SOURCE_MANIFEST.json',json.dumps(manifest,indent=2))
    temporary.replace(archive)
    (destination/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination/'SHA256SUMS.txt').write_text(f'{checksum}  {archive.name}\n')
    print(json.dumps({'archive':str(archive),'source_files':len(files),'bytes':archive.stat().st_size,'sha256':checksum},indent=2))


if __name__=='__main__':main()
