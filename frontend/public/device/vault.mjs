export const FILE_LIMIT = 20 * 1024 * 1024;
export const TOTAL_LIMIT = 256 * 1024 * 1024;
const RECORD_LIMIT = 300;
const HEADER_LIMIT = 6 * 1024 * 1024;
const magic = 'PPSTUDIO1\n';
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal: true});

export function openVault() {
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open('pastpaper-device', 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore('papers', {keyPath: 'id'});
    opening.onblocked = () => reject(new Error('请关闭其他工作区标签页后重试。'));
    opening.onerror = () => reject(new Error('无法打开本地存储，请检查浏览器设置。'));
    opening.onsuccess = () => {
      opening.result.onversionchange = () => opening.result.close();
      resolve(opening.result);
    };
  });
}

function useStore(db, mode, work) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('papers', mode);
    let result, failure;
    tx.oncomplete = () => resolve(result);
    tx.onabort = () => reject(failure || tx.error || new Error('存储操作未完成。'));
    const fail = error => { failure = error; tx.abort(); };
    work(tx.objectStore('papers'), value => { result = value; }, fail);
  });
}

export const listPapers = db => useStore(db, 'readonly', (store, done) => {
  const read = store.getAll();
  read.onsuccess = () => done(read.result.sort((a, b) => b.updated - a.updated));
});

export async function pdfBlob(file) {
  if (!file.size || file.size > FILE_LIMIT) throw new Error('PDF 必须小于或等于 20 MB。');
  const head = new TextDecoder().decode(await file.slice(0, 8).arrayBuffer());
  if (!/^%PDF-\d\.\d/.test(head)) throw new Error('无法识别这个 PDF 文件。');
  return file.slice(0, file.size, 'application/pdf');
}

function identifier() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
}

export async function newPaper(file, name = file.name) {
  const blob = await pdfBlob(file);
  if (typeof name !== 'string' || !name.trim() || name.length > 255 || /[\x00-\x1f/\\]/.test(name)) throw new Error('PDF 文件名无效。');
  return {id: identifier(), name, notes: '', draft: '', updated: Date.now(), blob};
}

export function addPapers(db, papers) {
  return useStore(db, 'readwrite', (store, done, fail) => {
    const current = store.getAll();
    current.onsuccess = () => {
      const ids = new Set(current.result.map(p => p.id));
      const incoming = papers.filter(p => !ids.has(p.id));
      const size = [...current.result, ...incoming].reduce((total, p) => total + p.blob.size, 0);
      if (size > TOTAL_LIMIT || current.result.length + incoming.length > RECORD_LIMIT) {
        fail(new Error('设备题库上限为 300 份 PDF、256 MB；请先备份和清理。'));
        return;
      }
      for (const record of incoming) store.add(record);
      done(incoming.length);
    };
  });
}

export function saveDraft(db, id, notes, draft) {
  return useStore(db, 'readwrite', (store, done, fail) => {
    const current = store.get(id);
    current.onsuccess = () => {
      if (!current.result) return fail(new Error('此记录已被另一个标签页移除。'));
      store.put({...current.result, notes, draft, updated: Date.now()});
      done();
    };
  });
}

export const removePaper = (db, id) => useStore(db, 'readwrite', store => store.delete(id));

async function digest(blob) {
  if (!crypto.subtle) return null;
  const bytes = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, '0')).join('');
}

export async function backup(db) {
  const papers = await listPapers(db);
  const records = [];
  for (const {id, name, notes, draft, updated, blob} of papers) {
    records.push({id, name, notes, draft, updated, size: blob.size, sha256: await digest(blob)});
  }
  const manifest = encoder.encode(JSON.stringify({version: 1, records}));
  if (manifest.byteLength > HEADER_LIMIT) throw new Error('备份索引超出大小限制。');
  const length = new Uint8Array(4);
  new DataView(length.buffer).setUint32(0, manifest.byteLength);
  return new Blob([magic, length, manifest, ...papers.map(p => p.blob)], {type: 'application/octet-stream'});
}

export async function restoreBackup(db, file) {
  const offset = magic.length + 4;
  const invalid = new Error('备份格式无效、损坏或超出上限。现有记录未更改。');
  if (file.size < offset || file.size > TOTAL_LIMIT + HEADER_LIMIT + offset) throw invalid;
  const head = await file.slice(0, offset).arrayBuffer();
  if (decoder.decode(head.slice(0, magic.length)) !== magic) throw invalid;
  const length = new DataView(head).getUint32(magic.length);
  if (!length || length > HEADER_LIMIT || offset + length > file.size) throw invalid;
  let manifest;
  try { manifest = JSON.parse(decoder.decode(await file.slice(offset, offset + length).arrayBuffer())); }
  catch { throw invalid; }
  if (manifest?.version !== 1 || !Array.isArray(manifest.records) || manifest.records.length > RECORD_LIMIT) throw invalid;
  const ids = new Set(), papers = [];
  let cursor = offset + length;
  for (const row of manifest.records) {
    if (!row || typeof row.id !== 'string' || !/^[0-9a-f]{32}$/.test(row.id) || ids.has(row.id) ||
        typeof row.name !== 'string' || !row.name.trim() || row.name.length > 255 || /[\x00-\x1f/\\]/.test(row.name) ||
        typeof row.notes !== 'string' || row.notes.length > 8000 || typeof row.draft !== 'string' || row.draft.length > 8000 ||
        !Number.isSafeInteger(row.updated) || row.updated < 0 || row.updated > 8.64e15 || !Number.isSafeInteger(row.size) ||
        row.size < 1 || row.size > FILE_LIMIT || cursor + row.size > file.size ||
        (row.sha256 !== null && (typeof row.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(row.sha256)))) throw invalid;
    const blob = await pdfBlob(file.slice(cursor, cursor + row.size));
    if (row.sha256 && (!crypto.subtle || row.sha256 !== await digest(blob))) throw new Error('备份校验失败。带校验值的备份请在 HTTPS 或本机地址导入。');
    papers.push({id: row.id, name: row.name, notes: row.notes, draft: row.draft, updated: row.updated, blob});
    ids.add(row.id);
    cursor += row.size;
  }
  if (cursor !== file.size || cursor - offset - length > TOTAL_LIMIT) throw invalid;
  return addPapers(db, papers);
}
