"""Bounded text extraction for editable classroom drafts, run in a child process."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pymupdf

MAX_TEXT = 120_000
MAX_PAGES = 20
MAX_IMAGE_PIXELS = 12_000_000
QUESTION = re.compile(r'^\s*(?:Question\s+)?([1-9]\d?)[.)\s]+(.+)',re.I)
CHOICE = re.compile(r'^\s*([A-L])[.)]\s+(.+)$')
MARK = re.compile(r'\[(\d{1,2})\]\s*$')
WORD = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MATH = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'


def ocr(data):
    binary = shutil.which('tesseract') or '/opt/homebrew/bin/tesseract'
    result = subprocess.run([binary,'stdin','stdout','-l','eng+chi_sim','--psm','3'],
                            input=data,capture_output=True,timeout=12,check=True)
    return result.stdout.decode('utf-8',errors='replace')


def pdf_text(source):
    with pymupdf.open(source) as document:
        if document.needs_pass or not 1 <= len(document) <= MAX_PAGES:
            raise ValueError('unsupported PDF')
        pages = []
        for page in document:
            if page.rect.is_empty or page.rect.is_infinite:
                raise ValueError('invalid geometry')
            text = page.get_text(sort=True).strip()
            if len(text) < 40 and page.get_images():
                scale = min(2.5, 1600/page.rect.width, 2200/page.rect.height)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                text = ocr(pix.tobytes('png'))
            pages.append(text)
            if sum(map(len,pages)) > MAX_TEXT:
                raise ValueError('too much extracted text')
    return '\n'.join(pages)


def docx_text(source):
    with ZipFile(source) as archive:
        matches = [entry for entry in archive.infolist() if entry.filename=='word/document.xml']
        if len(matches)!=1 or matches[0].file_size>3_000_000:
            raise ValueError('unsupported DOCX')
        with archive.open(matches[0]) as stream:
            data=stream.read(3_000_001)
    decoded=data.decode('utf-8-sig')
    if len(data)>3_000_000 or re.search(r'<!\s*(DOCTYPE|ENTITY)',decoded,re.I):
        raise ValueError('unsafe DOCX markup')
    root=ET.fromstring(decoded)
    return '\n'.join(''.join(n.text or '' for n in p.iter() if n.tag in (WORD+'t',MATH+'t')) for p in root.iter(WORD+'p'))


def extract(source, kind):
    with source.open('rb') as stream:
        header=stream.read(8)
    if kind=='pdf' and header.startswith(b'%PDF-'):
        text=pdf_text(source)
    elif kind=='docx' and header.startswith(b'PK\x03\x04'):
        text=docx_text(source)
    elif (kind=='png' and header==b'\x89PNG\r\n\x1a\n') or (kind=='jpeg' and header.startswith(b'\xff\xd8\xff')):
        with pymupdf.open(source) as image:
            profiles=image[0].get_image_info()
            if len(profiles)!=1 or not 0<profiles[0]['width']*profiles[0]['height']<=MAX_IMAGE_PIXELS:
                raise ValueError('image too large')
        text=ocr(source.read_bytes())
    else:
        raise ValueError('invalid document signature')
    if not text.strip() or len(text)>MAX_TEXT:
        raise ValueError('no usable text or too much text')
    return text


def questions(text):
    lines=text.splitlines()
    positions=[]
    expected=1
    for i,line in enumerate(lines):
        match=QUESTION.match(line)
        if match and int(match[1])==expected:
            positions.append(i)
            expected+=1
    if len(positions)<2:
        positions=[0]
    if len(positions)>60:
        raise ValueError('too many questions')
    result=[]
    for index,start in enumerate(positions):
        section=lines[start:positions[index+1] if index+1<len(positions) else None]
        content='\n'.join(section).strip()
        if len(content)>8000:
            raise ValueError('question too long')
        marks=MARK.search(content)
        options=[(m[1],m[2]) for line in section if (m:=CHOICE.match(line))]
        is_choice=len(options)>=2 and all(option[0]==chr(65+i) for i,option in enumerate(options))
        if is_choice:
            content='\n'.join(line for line in section if not CHOICE.match(line)).strip()
        result.append({'text':content, 'kind':'single' if is_choice else 'short',
                       'marks':int(marks[1]) if marks and int(marks[1]) else 1,
                       'options':[item[1][:500] for item in options] if is_choice else [],'accepted':[],
                       'topic':'','case_sensitive':False,'ignore_punctuation':False,'tolerance':0,'partial_credit':False})
    return result


if __name__=='__main__':
    import json
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(25,26))
    source=Path(sys.argv[1])
    try:
        print(json.dumps(questions(extract(source,sys.argv[2])),ensure_ascii=False))
    except Exception:
        sys.exit(2)
