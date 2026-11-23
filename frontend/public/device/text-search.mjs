const PAGE_LIMIT = 100;
const HIT_LIMIT = 80;
const flatten = text => text.normalize('NFKC').replace(/\s+/g, ' ').trim();

// Use the same Cambridge 0580 topic vocabulary and mark bands as the host index.
export const topics = [
  ['Number', '数与运算', /number|fraction|decimal|percentage|percent|ratio|round|prime|factor|multiple|integer|temperature|time|cost|interest|standard form/i],
  ['Algebra and graphs', '代数与图像', /algebra|expression|equation|simplif|expand|factoris|function|sequence|inequal|quadratic|graph/i],
  ['Coordinate geometry', '坐标几何', /coordinate|gradient|midpoint|straight line|line equation/i],
  ['Geometry', '几何', /angle|circle|quadrilateral|polygon|parallel|construct|geometr|chord|rhombus|bearing|triangle/i],
  ['Mensuration', '测量', /area|volume|perimeter|circumference|cylinder|cone|sphere|surface|prism/i],
  ['Trigonometry', '三角学', /trigon|sine|cosine|tangent|sin\b|cos\b|tan\b|pythagor/i],
  ['Transformations and vectors', '变换与向量', /transform|reflect|rotat|translat|enlarge|vector/i],
  ['Probability', '概率', /probab|dice|random|likely|fair coin/i],
  ['Statistics', '统计', /mean|median|mode|range|frequency|histogram|statistic|scatter|pie chart|sample|cumulative/i],
];

function pageLines(items, viewport) {
  const positions = items.filter(item => item.str?.trim()).map(item => {
    const [x, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
    return {x, y, right: x + item.width, text: flatten(item.str)};
  }).sort((a, b) => a.y - b.y || a.x - b.x);
  const lines = [];
  for (const item of positions) {
    const line = lines.at(-1);
    if (line && item.y - line.y <= 2.5) line.items.push(item);
    else lines.push({y: item.y, items: [item]});
  }
  return lines.map(({y, items}) => {
    items.sort((a, b) => a.x - b.x);
    return {y, x: items[0].x, text: items.map(item => item.text).join(' '), items};
  });
}

function questionParts(lines, viewport) {
  const {width, height} = viewport;
  if (viewport.rotation !== 0) return [];
  const roots = [];
  for (const [index, line] of lines.entries()) {
    if (line.y < 60 || line.y > height - 65 || line.x < 35 || line.x >= 65) continue;
    const number = line.text.match(/^([1-9]\d?)(?:\s|$)/)?.[1];
    if (number) roots.push({index, number});
  }
  // Page layouts with uncertain numbering, no printed marks or continuation-only
  // content remain searchable using an original-page preview.
  if (!roots.length || roots.some((root, i) => i && Number(root.number) !== Number(roots[i - 1].number) + 1)) return [];
  const result = [];
  for (const [i, root] of roots.entries()) {
    const end = roots[i + 1]?.index ?? lines.findIndex(line => line.y > height - 65);
    const body = lines.slice(root.index, end < 0 ? undefined : end);
    const parts = [];
    for (const [index, line] of body.entries()) {
      const marker = index === 0 ? line.text.match(/^\d+\s+(\([a-z]\))(?:\s|$)/i) : line.x >= 65 && line.x < 87 && line.text.match(/^(\([a-z]\))(?:\s|$)/i);
      if (marker) parts.push({index, letter: marker[1].toLowerCase()});
    }
    if (parts.some((part, index) => part.letter.charCodeAt(1) !== 97 + index)) return [];
    const shared = body.slice(0, parts[0]?.index ?? 0);
    const context = shared.length ? [Math.max(0, shared[0].y - 14), body[parts[0].index].y - 12] : null;
    const sections = parts.length ? parts : [{index: 0, letter: ''}];
    for (const [j, part] of sections.entries()) {
      const segment = body.slice(part.index, sections[j + 1]?.index);
      const printedMarks = segment.flatMap(line => line.items.flatMap(item => {
        const value = item.right >= width * .8 && item.text.match(/\[(\d{1,2})\]$/)?.[1];
        return value ? [{value: Number(value), y: line.y}] : [];
      }));
      if (printedMarks.length !== 1) return [];
      const [mark] = printedMarks;
      const bottom = Math.min(height, mark.y + 14, (body[sections[j + 1]?.index]?.y ?? Infinity) - 12);
      const top = Math.max(0, segment[0].y - 14);
      if (bottom <= top) return [];
      result.push({
        label: root.number + part.letter,
        marks: mark.value,
        text: [...shared, ...segment.filter(line => line.y <= bottom)].map(line => line.text).join('\n'),
        regions: context && context[1] > context[0] ? [context, [top, bottom]] : [[top, bottom]],
      });
    }
  }
  return result;
}

async function renderPage(page, viewport, signal) {
  const scale = Math.min(1.4, 800 / viewport.width, 1050 / viewport.height);
  const scaled = page.getViewport({scale});
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(scaled.width);
  canvas.height = Math.ceil(scaled.height);
  const task = page.render({canvas, viewport: scaled, annotationMode: 0});
  const cancel = () => task.cancel();
  signal.addEventListener('abort', cancel, {once: true});
  try { await task.promise; } finally { signal.removeEventListener('abort', cancel); }
  return {canvas, scale};
}

async function previewImages(rendered, regions) {
  const {canvas, scale} = rendered;
  if (!regions) return [await new Promise(resolve => canvas.toBlob(resolve, 'image/png'))].filter(Boolean);
  const images = [];
  const crop = document.createElement('canvas');
  const left = Math.round(28 * scale);
  for (const [top, bottom] of regions) {
    crop.width = canvas.width - left * 2;
    crop.height = Math.max(1, Math.round((bottom - top) * scale));
    crop.getContext('2d').drawImage(canvas, left, Math.round(top * scale), crop.width, crop.height, 0, 0, crop.width, crop.height);
    const blob = await new Promise(resolve => crop.toBlob(resolve, 'image/png'));
    if (blob) images.push(blob);
  }
  return images;
}

export async function searchPages(papers, {query, topic, difficulty, maxMarks}, {signal, onProgress, onHit}) {
  const needle = flatten(query).toLowerCase();
  let pdfjs;
  try { pdfjs = await import('./pdf-engine/pdf.min.mjs'); }
  catch { throw new Error('无法加载本地解析组件。首次使用请联网并重新打开工作区。'); }
  pdfjs.GlobalWorkerOptions.workerSrc = new URL('./pdf-engine/pdf.worker.min.mjs', import.meta.url).href;
  const standardFontDataUrl = new URL('./pdf-engine/standard-fonts/', import.meta.url).href;
  const stats = {scanned: 0, noText: 0, failed: 0, truncated: false};
  let hits = 0;
  for (const paper of papers) {
    signal.throwIfAborted();
    onProgress(stats.scanned + 1, papers.length);
    const data = new Uint8Array(await paper.blob.arrayBuffer());
    signal.throwIfAborted();
    const task = pdfjs.getDocument({data, standardFontDataUrl, useWasm: false, enableXfa: false, disableFontFace: true, useSystemFonts: false, isEvalSupported: false});
    const abort = () => { void task.destroy().catch(() => {}); };
    signal.addEventListener('abort', abort, {once: true});
    try {
      const document = await task.promise;
      const end = Math.min(document.numPages, PAGE_LIMIT);
      let hasText = false;
      for (let pageNumber = 1; pageNumber <= end; pageNumber++) {
        signal.throwIfAborted();
        const page = await document.getPage(pageNumber);
        const {items} = await page.getTextContent();
        const viewport = page.getViewport({scale: 1});
        const lines = pageLines(items, viewport);
        if (!lines.length) continue;
        hasText = true;
        const cambridge = paper.info?.subject === '0580' && paper.info.kind === 'qp';
        const parts = cambridge ? questionParts(lines, viewport) : [];
        const wholePage = {text: lines.map(line => line.text).join('\n')};
        const candidates = parts.length ? parts : [wholePage];
        const matches = candidates.filter(part => {
          part.topics = cambridge ? topics.filter(([, , pattern]) => pattern.test(part.text)).slice(0, 3) : [];
          part.difficulty = part.marks == null ? '' : part.marks <= 2 ? 'easy' : part.marks <= 4 ? 'medium' : 'hard';
          const searchable = flatten([part.text, part.label || '', ...part.topics.flatMap(([name, zh]) => [name, zh])].join(' ')).toLowerCase();
          return (!needle || searchable.includes(needle)) && (!topic || part.topics.some(([name]) => name === topic)) &&
            (!difficulty || part.difficulty === difficulty) && (!maxMarks || (part.marks != null && part.marks <= maxMarks));
        });
        if (parts.length && !matches.length && needle && !topic && !difficulty && !maxMarks && flatten(wholePage.text).toLowerCase().includes(needle)) {
          matches.push({...wholePage, topics: []});
        }
        if (matches.length) {
          let rendered;
          try { rendered = await renderPage(page, viewport, signal); }
          catch { signal.throwIfAborted(); }
          for (const part of matches) {
            const images = rendered ? await previewImages(rendered, part.regions) : [];
            signal.throwIfAborted();
            onHit(paper, pageNumber, part, images);
            if (++hits >= HIT_LIMIT) { stats.truncated = true; break; }
          }
        }
        page.cleanup();
        if (stats.truncated) break;
      }
      if (!hasText) stats.noText++;
    } catch {
      signal.throwIfAborted();
      stats.failed++;
    } finally {
      signal.removeEventListener('abort', abort);
      if (!signal.aborted) await task.destroy();
    }
    stats.scanned++;
    if (stats.truncated) break;
  }
  return stats;
}
