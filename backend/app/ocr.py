"""Offline OCR sidecars; never write to a source PDF."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import pymupdf

STATES = {}
LOCK = threading.RLock()

def cache_path(page):
    source = Path(page.parent.name)
    stat = source.stat()
    key = hashlib.sha256(f'{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:ocr-v4'.encode()).hexdigest()
    root = Path(os.environ.get('PASTPAPER_DATA_DIR', Path(__file__).resolve().parents[1] / 'data')) / 'ocr'
    root.mkdir(parents=True, exist_ok=True)
    return root / f'{key}-{page.number}.json'

def native_lines(page):
    return [{'text': ''.join(s['text'] for s in line['spans']).strip(), 'bbox': list(line['bbox'])}
            for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])
            if ''.join(s['text'] for s in line['spans']).strip()]

def read_lines(page):
    native = native_lines(page)
    body=[l for l in native if 35<=l['bbox'][0]<page.rect.width-35 and 60<=l['bbox'][1]<page.rect.height-55]
    if sum(len(l['text']) for l in body) >= 40 or not page.get_images():
        return native
    with LOCK:
        cache = cache_path(page)
        name=str(Path(page.parent.name).resolve())
        STATES.setdefault(name,{'status':'ready','page':0,'total':len(page.parent),'error':''})
        if cache.exists():
            STATES[name].update(page=max(STATES[name]['page'],page.number+1))
            return json.loads(cache.read_text())['lines']
        binary = shutil.which('tesseract') or ('/opt/homebrew/bin/tesseract' if Path('/opt/homebrew/bin/tesseract').exists() else None)
        if not binary: raise ValueError('扫描件需要本地 Tesseract；请运行 brew install tesseract tesseract-lang')
        STATES[name] = {'status':'running', 'page':page.number+1, 'total':len(page.parent), 'error':''}
        try:
            scale = 3
            clip=pymupdf.Rect(35,35,page.rect.width-35,page.rect.height-35) if page.rect.width>200 and page.rect.height>300 else page.rect
            from .render_limits import check_render_size
            check_render_size(clip,scale)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
            result = subprocess.run([binary,'stdin','stdout','-l','eng+chi_sim','--psm','3','tsv'], input=pix.tobytes('png'), capture_output=True, timeout=120)
            if result.returncode: raise ValueError('本地 OCR 失败：'+result.stderr.decode(errors='replace')[-250:])
            lines=parse_tsv(result.stdout.decode(),scale,clip)
            source_name=Path(page.parent.name).stem.lower()
            if '_qp_' in source_name or source_name=='qp':
                margin=pymupdf.Rect(35,60,66,page.rect.height-65)
                image=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=margin,alpha=False)
                focused=subprocess.run([binary,'stdin','stdout','-l','eng','--psm','6','-c','tessedit_char_whitelist=0123456789','tsv'],input=image.tobytes('png'),capture_output=True,timeout=30)
                if not focused.returncode:
                    for line in parse_tsv(focused.stdout.decode(),scale,margin):
                        if line['text'].isdigit() and len(line['text'])<=2 and line['confidence']>25 and not any(l['text']==line['text'] and abs(l['bbox'][1]-line['bbox'][1])<8 for l in lines):lines.append(line)
            data={'lines':lines, 'engine':'Tesseract', 'review_required':True}
            tmp=cache.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False));tmp.replace(cache)
            STATES[name].update(status='ready')
            return lines
        except Exception as exc:
            STATES[name].update(status='failed',error=str(exc));raise

def join_words(words):
    return {'text':' '.join(w['text'] for w in words), 'bbox':[min(w['bbox'][0] for w in words),min(w['bbox'][1] for w in words),max(w['bbox'][2] for w in words),max(w['bbox'][3] for w in words)], 'confidence':min(w['confidence'] for w in words), 'ocr':True}

def text_in(page,rect=None):
    if not rect: return '\n'.join(l['text'] for l in read_lines(page))
    r=pymupdf.Rect(rect)
    return '\n'.join(l['text'] for l in read_lines(page) if r.contains(pymupdf.Point((l['bbox'][0]+l['bbox'][2])/2,(l['bbox'][1]+l['bbox'][3])/2)))


def parse_tsv(data,scale,clip):
    groups={}
    for word in csv.DictReader(io.StringIO(data),delimiter='\t'):
        if word['level']!='5' or not word['text'].strip():continue
        x,y,w,h=[float(word[k])/scale for k in ('left','top','width','height')]
        x+=clip.x0;y+=clip.y0
        key=tuple(word[k] for k in ('block_num','par_num','line_num'))
        groups.setdefault(key,[]).append({'text':word['text'],'bbox':[x,y,x+w,y+h],'confidence':float(word['conf'])})
    lines=[]
    for words in groups.values():
        current=[]
        for word in sorted(words,key=lambda w:w['bbox'][0]):
            if current and word['bbox'][0]-current[-1]['bbox'][2]>18:
                lines.append(join_words(current));current=[]
            current.append(word)
        if current:lines.append(join_words(current))
    return sorted(lines,key=lambda l:(l['bbox'][1],l['bbox'][0]))
