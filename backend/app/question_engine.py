"""Layout-based Cambridge question extraction; originals remain authoritative."""
from __future__ import annotations
import json
import math
import re
from pathlib import Path
import pymupdf
from .ocr import read_lines, text_in

SYLLABUS_URL = 'https://www.cambridgeinternational.org/Images/662466-2025-2027-syllabus.pdf'
TOPICS = [
 ('Number', '数与运算', r'number|fraction|decimal|percentage|percent|ratio|round|prime|factor|multiple|integer|temperature|time|cost|interest|standard form'),
 ('Algebra and graphs', '代数与图像', r'algebra|expression|equation|simplif|expand|factoris|function|sequence|inequal|quadratic|graph'),
 ('Coordinate geometry', '坐标几何', r'coordinate|gradient|midpoint|straight line|line equation'),
 ('Geometry', '几何', r'angle|circle|quadrilateral|polygon|parallel|construct|geometr|chord|rhombus|bearing|triangle'),
 ('Mensuration', '测量', r'area|volume|perimeter|circumference|cylinder|cone|sphere|surface|prism'),
 ('Trigonometry', '三角学', r'trigon|sine|cosine|tangent|sin\b|cos\b|tan\b|pythagor'),
 ('Transformations and vectors', '变换与向量', r'transform|reflect|rotat|translat|enlarge|vector'),
 ('Probability', '概率', r'probab|dice|random|likely|fair coin'),
 ('Statistics', '统计', r'mean|median|mode|range|frequency|histogram|statistic|scatter|pie chart|sample|cumulative'),
]


def lines_of(page):
    return sorted(read_lines(page), key=lambda x: (round(x['bbox'][1], 0), x['bbox'][0]))


def bounds(page):
    # Cambridge portrait QP includes header, margin codes and a footer outside this body.
    return 40, 60, page.rect.width - 40, page.rect.height - 65


def segments_between(doc, start, end):
    result = []
    for p in range(start[0], end[0] + 1):
        x0, top, x1, bottom = bounds(doc[p])
        y0 = max(top, start[1] - 4) if p == start[0] else top
        y1 = min(bottom, end[1] - 4) if p == end[0] else bottom
        if y1 - y0 > 2:
            result.append({'page': p + 1, 'rect': [x0, y0, x1, y1]})
    return result


def segment_text(doc, segments):
    return '\n'.join(text_in(doc[s['page'] - 1], s['rect']).strip() for s in segments)


def classify(text):
    matches = [name for name, _, pattern in TOPICS if re.search(pattern, text, re.I)]
    return matches[:3]


def ms_rows(path):
    if not path or not Path(path).is_file():
        return {}
    rows = {}
    with pymupdf.open(path) as doc:
        for pi, page in enumerate(doc):
            lines = lines_of(page)
            headers = {l['text']: l for l in lines if l['text'] in ('Question', 'Answer', 'Marks', 'Partial Marks', 'Guidance')}
            if not all(k in headers for k in ('Question', 'Answer', 'Marks')):
                continue
            question_right = headers['Question']['bbox'][2] + 7
            answer_left = question_right + 2
            marks_left = headers['Marks']['bbox'][0] - 6
            markers = []
            for l in lines:
                x0, y0, x1, y1 = l['bbox']
                if l.get('ocr') and x1<question_right:
                    label=re.sub(r'\s+','',l['text'])
                    label=re.sub(r'^[lI](?=\()','1',label)
                    l={**l,'text':label}
                if x1 < question_right and y0 > headers['Question']['bbox'][3] + 4 and re.fullmatch(r'\d{1,2}(?:\([a-z]\))?(?:\([ivx]+\))?', l['text']):
                    markers.append(l)
            for index, marker in enumerate(markers):
                y0 = marker['bbox'][1] - 3
                y1 = markers[index + 1]['bbox'][1] - 3 if index + 1 < len(markers) else page.rect.height - 55
                rect = [max(35, headers['Question']['bbox'][0] - 12), y0, page.rect.width - 55, y1]
                answer_lines = [l for l in lines if answer_left <= l['bbox'][0] < marks_left and y0 <= l['bbox'][1] < y1]
                answer = '\n'.join(l['text'] for l in answer_lines)
                # Separate stacked numerators/denominators without pretending damaged formula text is exact.
                fraction = False
                if len(answer_lines) >= 2:
                    first, second = answer_lines[:2]
                    if re.fullmatch(r'\d+', first['text']) and re.match(r'^\d+(?:\s+(?:oe|cao))?$', second['text']) and second['bbox'][1] - first['bbox'][1] < 12:
                        answer = first['text'] + '/' + second['text'] + ('\n' + '\n'.join(l['text'] for l in answer_lines[2:]) if len(answer_lines) > 2 else '')
                        fraction = True
                marks = None
                for l in lines:
                    if y0 <= l['bbox'][1] < y0 + 15 and abs(l['bbox'][0] - (headers['Marks']['bbox'][0] + 27)) < 25:
                        m = re.match(r'^(\d+)\b', l['text'])
                        if m:
                            marks = int(m.group(1)); break
                guidance = text_in(page, [marks_left + 35, y0, page.rect.width - 55, y1])
                rows[marker['text']] = {'segments': [{'page': pi + 1, 'rect': rect}], 'answer': answer.strip(), 'guidance': guidance.strip(), 'marks': marks, 'ocr_used':any(l.get('ocr') for l in lines), 'formula_review': fraction or any('�' in l['text'] for l in answer_lines)}
    return rows


def extract_questions(qp_path, ms_path=None):
    official = ms_rows(ms_path)
    with pymupdf.open(qp_path) as doc:
        all_lines = [lines_of(p) for p in doc]
        main = []
        expected = 1
        for pi, lines in enumerate(all_lines):
            for line in lines:
                x0, y0, _, _ = line['bbox']
                m = re.match(r'^(\d{1,2})(?:\s|$)', line['text'])
                if m and 35 <= x0 < 65 and 60 <= y0 < doc[pi].rect.height - 65 and int(m.group(1)) == expected:
                    aligned=min([y0]+[l['bbox'][1] for l in lines if 65<=l['bbox'][0]<115 and abs(l['bbox'][1]-y0)<4])
                    main.append((str(expected), (pi, aligned)))
                    expected += 1
        if not main:
            raise ValueError('没有可靠识别题号；扫描件或不同排版请使用人工编辑，系统不会猜造题目。')
        last_page = max((pi for pi, page in enumerate(doc) if re.search(r'\[\d+\]', text_in(page))), default=main[-1][1][0])
        final_end = (last_page, doc[last_page].rect.height - 61)
        questions = []
        for qi, (root, start) in enumerate(main):
            end = main[qi + 1][1] if qi + 1 < len(main) else final_end
            markers = [{'label': root, 'parent': None, 'start': start}]
            letter = None
            for pi in range(start[0], end[0] + 1):
                for line in all_lines[pi]:
                    x0, y0, _, _ = line['bbox']; pos = (pi, y0)
                    if pos < start or pos >= end:
                        continue
                    # Cambridge part letters are inset one tab; roman labels one more tab.
                    marker_text = line['text']
                    if 35 <= x0 < 65 and re.match(r'^' + root + r'\s+\(', marker_text):
                        marker_text = re.sub(r'^' + root + r'\s+', '', marker_text)
                        x0 = 72
                    a = re.match(r'^\(([a-hj-z])\)(?:\s|$)', marker_text)
                    roman = re.match(r'^\(([ivx]+)\)(?:\s|$)', marker_text)
                    if a and 65 <= x0 < 86:
                        letter = f'{root}({a.group(1)})'
                        markers.append({'label': letter, 'parent': root, 'start': pos})
                        both = re.search(r'^\([a-z]\)\s*\(([ivx]+)\)', marker_text)
                        if both:
                            markers.append({'label': letter + '(' + both.group(1) + ')', 'parent': letter, 'start': pos})
                    elif roman and 83 <= x0 < 115:
                        parent = letter or root
                        markers.append({'label': parent + '(' + roman.group(1) + ')', 'parent': parent, 'start': pos})
            for mi, marker in enumerate(markers):
                descendants = [m for m in markers if m['parent'] == marker['label']]
                boundary = next((m['start'] for m in markers[mi + 1:] if len(m['label']) <= len(marker['label']) or m['parent'] == marker['parent']), end)
                own_end = descendants[0]['start'] if descendants else boundary
                body = segments_between(doc, marker['start'], boundary)
                context = []
                ancestor = marker['parent']
                while ancestor:
                    am = next(m for m in markers if m['label'] == ancestor)
                    children = [m for m in markers if m['parent'] == ancestor]
                    if children and am['start'] < children[0]['start']:
                        context = segments_between(doc, am['start'], children[0]['start']) + context
                    ancestor = am['parent']
                text = segment_text(doc, body)
                full_text = segment_text(doc, context) + '\n' + text
                scheme = official.get(marker['label'], {})
                found_marks = [int(m) for m in re.findall(r'\[(\d+)\]', text)]
                marks = scheme.get('marks') if scheme.get('marks') is not None else sum(found_marks) or None
                questions.append({'label': marker['label'], 'parent_label': marker['parent'], 'root_label': root, 'leaf': not descendants,
                    'segments': body, 'context_segments': context, 'stem': full_text.strip(), 'marks': marks,
                    'ms_segments': scheme.get('segments', []), 'official_answer': scheme.get('answer', ''), 'official_guidance': scheme.get('guidance', ''),
                    'topic_auto': classify(full_text), 'difficulty': 'easy' if marks and marks <= 2 else 'medium' if marks and marks <= 4 else 'hard' if marks else 'unknown',
                    'review_status': 'pending', 'ocr_used':scheme.get('ocr_used',False) or any(l.get('ocr') for lines in all_lines for l in lines), 'formula_review': scheme.get('formula_review', False) or any(l.get('ocr') for lines in all_lines for l in lines)})
        return questions


def validate_segments(path, segments):
    with pymupdf.open(path) as doc:
        for s in segments:
            if not isinstance(s.get('page'), int) or not 1 <= s['page'] <= len(doc):
                raise ValueError('页码超出 PDF 范围')
            rect = s.get('rect', [])
            if len(rect) != 4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in rect):
                raise ValueError('截图范围必须是四个坐标')
            r = pymupdf.Rect(rect)
            if r.is_empty or r.is_infinite or not doc[s['page'] - 1].rect.contains(r):
                raise ValueError('截图范围超出 PDF 页面')


def crop_png(path, segment):
    validate_segments(path, [segment])
    with pymupdf.open(path) as doc:
        from .render_limits import check_render_size
        check_render_size(pymupdf.Rect(segment['rect']),1.7)
        return doc[segment['page'] - 1].get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), clip=pymupdf.Rect(segment['rect']), alpha=False).tobytes('png')
