import {applyPreferences,errorCopy,language,localCopy,t} from "./locale.mjs";
import {openVault, listPapers, addPapers, newPaper, pdfBlob, saveDraft, removePaper, backup, restoreBackup} from './vault.mjs';
import {runtime} from './providers.mjs';
import {searchPages, topics} from './text-search.mjs';

const $ = id => document.getElementById(id);
applyPreferences();
const db = openVault();
let papers = [], selected, activeRuntime, connection, aiRequest, questionJob, reviewKey = '', cursor = '', sharingReady = false;
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('pastpaper-device-refresh') : null;
const message = (copy, error = false) => {
  localCopy($('message'),typeof copy==='function'?copy:()=>copy);
  $('message').hidden = !$('message').textContent;
  $('message').toggleAttribute('data-error', error);
};
const errorText = error => error?.name === 'QuotaExceededError' ? t("浏览器存储空间不足。请备份后腾出空间。") : errorCopy(error?.message);
async function act(run, control) {
  message('');
  if (control) control.disabled = true;
  try { await run(); } catch (error) { message(() => errorText(error), true); }
  finally { if (control) control.disabled = false; }
}

function button(text, action, kind) {
  const node = document.createElement('button');
  node.type = 'button';
  localCopy(node, () => t(text));
  if (kind) node.className = kind;
  node.onclick = () => void act(action, node);
  return node;
}

function row(name, detail, ...actions) {
  const item = document.createElement('li'), text = document.createElement('div');
  const title = document.createElement('strong'), sub = document.createElement('small'), controls = document.createElement('div');
  title.textContent = name; localCopy(sub, () => typeof detail==='function'?detail():detail); text.append(title, sub);
  controls.className = 'actions'; controls.append(...actions); item.append(text, controls);
  return item;
}

const mb = bytes => `${(bytes / 1048576).toFixed(1)} MB`;
function metadata(name) {
  const match = /^(\d{4})_([msw])(\d{2})_(qp|ms)_(\d{1,2})\b/i.exec(name);
  if (!match) return null;
  const [, subject, season, shortYear, kind, number] = match.map(value => value.toLowerCase());
  const year = Number(shortYear) + (Number(shortYear) < 80 ? 2000 : 1900);
  const level = subject === '0580' ? {1: 'Core', 2: 'Core', 3: 'Extended', 4: 'Extended'}[number[0]] : undefined;
  const exam = `${subject}/${number} · ${{m: 'Feb/March', s: 'May/June', w: 'Oct/Nov'}[season]} ${year}${level ? ' · ' + level : ''}`;
  return {key: `${subject}_${season}${shortYear}_${number}`, subject, kind, year, level, exam};
}

function downloadBlob(blob, name, preview = false, page) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = page ? `${url}#page=${page}` : url;
  if (preview) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
  else link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function selectPaper(p) {
  selected = p.id;
  $('edit-title').textContent = p.name;
  $('notes').value = p.notes;
  $('draft').value = p.draft;
  $('editor').hidden = false;
  $('notes').focus();
}

function renderPapers() {
  const query = $('search').value.trim().toLowerCase();
  const shown = papers.filter(p => (p.name + '\n' + p.notes).toLowerCase().includes(query));
  const paired = new Map();
  for (const {name} of papers) {
    const info = metadata(name);
    if (info) paired.set(info.key, (paired.get(info.key) || 0) | (info.kind === 'qp' ? 1 : 2));
  }
  $('papers').replaceChildren(...shown.map(p => {
    const info = metadata(p.name);
    const detail = () => info ? `${info.exam} · ${t(info.kind === 'qp' ? "试卷" : "评分细则")}${paired.get(info.key) === 3 ? t(" · 已配对") : ''} · ${mb(p.blob.size)}` : mb(p.blob.size);
    return row(p.name, detail, button("打开 PDF", () => downloadBlob(p.blob, p.name, true)), button("笔记与草稿", () => selectPaper(p)));
  }));
  $('empty').hidden = papers.length > 0;
  $('no-papers').hidden = !papers.length || shown.length > 0;
  localCopy($('count'), () => query ? t("{0} / {1} 份 PDF",shown.length,papers.length) : t("{0} 份 PDF",papers.length));
  const usage = mb(papers.reduce((sum, p) => sum + p.blob.size, 0));
  localCopy($('usage'), () => t("当前浏览器保存 {0} 份 PDF，共 {1}。",papers.length,usage));
}

async function refresh(localChange = false) {
  papers = await listPapers(await db);
  const scope = $('question-scope').value;
  $('question-scope').replaceChildren(localCopy(new Option('', ''), () => t("最近的 40 份试卷")), ...papers.map(p => new Option(p.name, p.id)));
  if (papers.some(p => p.id === scope)) $('question-scope').value = scope;
  if (!papers.some(p => p.id === selected)) closeEditor();
  renderPapers();
  if (localChange) channel?.postMessage('updated');
}

const resultImages = new Set();
for (const [value, name] of topics) $('question-topic').add(localCopy(new Option('', value), () => language==='en'?value:`${name} · ${value}`));

function questionCard(paper, page, part, images, markSchemeId) {
  const item = document.createElement('li');
  item.className = 'panel question-result';
  const header = document.createElement('header');
  const title = document.createElement('h2');
  localCopy(title, () => part.label ? `Question ${part.label}` : t("第 {0} 页",page));
  const state = document.createElement('small');
  localCopy(state, () => part.label ? t("{0} 分 · 待核对",part.marks) : t("原页预览"));
  header.append(title, state);
  const source = document.createElement('small');
  localCopy(source, () => t("{0} · 第 {1} 页",paper.info?.exam || paper.name,page));
  item.append(header, source);
  if (images.length) {
    const figures = document.createElement('figure');
    figures.className = 'question-figures';
    for (const [index, blob] of images.entries()) {
      const image = document.createElement('img');
      localCopy(image, () => `${title.textContent} · ${images.length > 1 && index === 0 ? t("共用题干") : t("原题截图")}`, 'alt');
      image.src = URL.createObjectURL(blob);
      resultImages.add(image.src);
      image.loading = 'lazy';
      figures.append(image);
    }
    item.append(figures);
  } else {
    const status = document.createElement('small');
    localCopy(status, () => t("截图暂不可用，可打开原始 PDF。"));
    item.append(status);
  }
  const details = document.createElement('details'), summary = document.createElement('summary'), excerpt = document.createElement('p');
  localCopy(summary, () => t("查看提取文字"));
  excerpt.textContent = part.text.length > 2400 ? part.text.slice(0, 2400) + '…' : part.text;
  details.append(summary, excerpt);
  item.append(details);
  if (part.topics.length) {
    const tags = document.createElement('div');
    tags.className = 'actions';
    for (const [name] of part.topics) {
      const tag = document.createElement('span');
      tag.className = 'badge'; tag.textContent = name; tags.append(tag);
    }
    item.append(tags);
  }
  function openFile(id, pageNumber) {
    const available = papers.find(p => p.id === id);
    if (!available) throw new Error(t("该 PDF 已从私人题库移除。"));
    downloadBlob(available.blob, available.name, true, pageNumber);
  }
  const controls = document.createElement('div');
  controls.className = 'actions';
  controls.append(button("查看原题", () => openFile(paper.id, page)));
  if (markSchemeId) controls.append(button("官方评分细则", () => openFile(markSchemeId)));
  controls.append(button("笔记与草稿", () => {
    const available = papers.find(p => p.id === paper.id);
    if (!available) throw new Error(t("该 PDF 已从私人题库移除。"));
    showView(document.querySelector('[data-view="library"]'));
    selectPaper(available);
  }));
  item.append(controls);
  return item;
}

$('stop-search').onclick = () => questionJob?.abort();
$('question-form').onsubmit = async event => {
  event.preventDefault();
  if (questionJob) return;
  const query = $('question-query').value.trim();
  const topic = $('question-topic').value, difficulty = $('question-difficulty').value;
  const subject = $('question-subject').value, level = $('question-level').value;
  const year = $('question-year').valueAsNumber, maxMarks = $('question-marks').valueAsNumber;
  const selectedPaper = $('question-scope').value;
  const results = $('question-results'), status = $('question-status');
  for (const url of resultImages) URL.revokeObjectURL(url);
  resultImages.clear();
  results.replaceChildren();
  if (!query && !topic && !difficulty && !subject && !level && !year && !maxMarks && !selectedPaper) {
    localCopy(status, () => t("输入关键词或选择筛选项开始搜索。"));
    return;
  }
  const catalog = papers.map(p => ({...p, info: metadata(p.name)}));
  const schemes = new Map(catalog.filter(p => p.info?.kind === 'ms').reverse().map(p => [p.info.key, p.id]));
  const candidates = catalog.filter(p =>
    (selectedPaper ? p.id === selectedPaper : p.info?.kind !== 'ms') &&
    (!subject || p.info?.subject === subject) && (!level || p.info?.level === level) &&
    (!year || (p.info && p.info.year >= year))
  ).slice(0, 40);
  if (!candidates.length) {
    localCopy(status, () => papers.length ? t("没有符合筛选条件的试卷。") : t("先在私人题库导入 PDF，再搜索正文。"));
    return;
  }
  const job = questionJob = new AbortController();
  const timer = setTimeout(() => job.abort(), 35_000);
  let count = 0;
  $('find-questions').disabled = true; $('stop-search').hidden = false;
  localCopy(status, () => t("正在准备本机解析…"));
  try {
    const stats = await searchPages(candidates, {query, topic, difficulty, maxMarks}, {
      signal: job.signal,
      onProgress: (current, total) => { localCopy(status, () => t("正在搜索第 {0} / {1} 份 PDF…",current,total)); },
      onHit: (paper, page, part, images) => {
        count++;
        results.append(questionCard(paper, page, part, images, paper.info?.kind === 'qp' ? schemes.get(paper.info.key) : undefined));
      },
    });
    localCopy(status, () => t("已搜索 {0} 份 PDF，找到 {1} 个结果。{2}{3}{4}",stats.scanned,count,stats.noText ? t(" {0} 份未检出文本层。",stats.noText) : '',stats.failed ? t(" {0} 份无法读取。",stats.failed) : '',stats.truncated ? t(" 已达结果上限，可缩小搜索范围。") : ''));
  } catch (error) {
    localCopy(status, () => job.signal.aborted ? t("搜索已停止，保留 {0} 个结果。",count) : errorText(error));
  } finally {
    clearTimeout(timer); questionJob = undefined;
    $('find-questions').disabled = false; $('stop-search').hidden = true;
  }
};
function closeEditor() { selected = undefined; $('editor').hidden = true; }
if (channel) channel.onmessage = () => void act(() => refresh());
$('search').oninput = renderPapers;
$('close-editor').onclick = closeEditor;
$('pdfs').onchange = () => void act(async () => {
  const files = Array.from($('pdfs').files);
  $('pdfs').value = '';
  if (files.length > 20) throw new Error(t("每次最多导入 20 份 PDF。"));
  const entries = await Promise.all(files.map(file => newPaper(file)));
  await addPapers(await db, entries);
  await refresh(true);
  message(() => t("已在当前设备保存 {0} 份 PDF。",entries.length));
});
let folderEntries = [], folderIgnored = 0, folderBusy = false;
const folderLabels = {ready:"待导入",sending:"正在导入",completed:"已导入",failed:"导入失败"};
function renderFolder() {
  const complete=folderEntries.filter(entry=>entry.state==='completed').length;
  const failed=folderEntries.filter(entry=>entry.state==='failed').length;
  localCopy($('folder-summary'), () => t("找到 {0} 份 PDF · 已导入 {1} · 失败 {2} · 忽略 {3} 个其他文件",folderEntries.length,complete,failed,folderIgnored));
  const progress=$('folder-progress');
  progress.hidden=!folderBusy&&!complete&&!failed;
  progress.max=Math.max(1,folderEntries.filter(entry=>entry.selected||entry.state!=='ready').length);
  progress.value=complete+failed;
  $('folder-import').disabled=folderBusy||!folderEntries.some(entry=>entry.selected&&entry.state==='ready');
  $('folder-retry').hidden=!failed;
  $('folder-retry').disabled=folderBusy;
  $('folder-pdfs').disabled=folderBusy;
  $('folder-entries').replaceChildren(...folderEntries.map(entry=>{
    const item=document.createElement('li'), content=document.createElement('div'), label=document.createElement('label');
    const checkbox=document.createElement('input'), status=document.createElement('small');
    checkbox.type='checkbox';checkbox.checked=entry.selected;checkbox.disabled=folderBusy||entry.state!=='ready';
    checkbox.onchange=()=>{
      entry.selected=checkbox.checked;
      $('folder-import').disabled=!folderEntries.some(value=>value.selected&&value.state==='ready');
    };
    label.append(checkbox,entry.file.webkitRelativePath||entry.file.name);
    localCopy(status, () => t(folderLabels[entry.state])+(entry.error?' · '+errorText(entry.error):''));
    content.append(label,status);item.append(content);
    return item;
  }));
}
$('folder-pdfs').onchange=()=>{
  const files=Array.from($('folder-pdfs').files);
  $('folder-pdfs').value='';
  if(!files.length||folderBusy)return;
  folderEntries=files.filter(file=>file.name.toLowerCase().endsWith('.pdf')).map(file=>({file,selected:true,state:'ready'}));
  folderIgnored=files.length-folderEntries.length;
  $('folder-review').hidden=false;
  renderFolder();
};
async function importDeviceFolder(retry) {
  if(folderBusy)return;
  const queue=folderEntries.filter(entry=>retry?entry.state==='failed':entry.selected&&entry.state==='ready');
  folderBusy=true;
  try {
    for(const entry of queue){
      entry.state='sending';entry.error='';renderFolder();
      try{
        await addPapers(await db,[await newPaper(entry.file)]);
        entry.state='completed';
      }catch(error){entry.state='failed';entry.error=error;}
    }
    await refresh(true);
  }finally{folderBusy=false;renderFolder();}
}
$('folder-import').onclick=()=>void act(()=>importDeviceFolder(false));
$('folder-retry').onclick=()=>void act(()=>importDeviceFolder(true));
$('editor').onsubmit = event => {
  event.preventDefault();
  void act(async () => { await saveDraft(await db, selected, $('notes').value, $('draft').value); await refresh(true); message(() => t("学习记录已在当前设备保存。")); }, event.submitter);
};
$('open-paper').onclick = () => {
  const p = papers.find(p => p.id === selected);
  if (p) downloadBlob(p.blob, p.name, true);
};
$('remove-paper').onclick = () => {
  if (selected && confirm(t("移除此浏览器中的 PDF 副本、笔记和草稿？原始文件不会被修改。"))) void act(async () => {
    await removePaper(await db, selected); closeEditor(); await refresh(true); message(() => t("已移除本地副本。"));
  });
};
$('export').onclick = () => void act(async () => downloadBlob(await backup(await db), 'PastPaper-Device.ppstudio'), $('export'));
$('restore').onchange = () => void act(async () => {
  const [file] = $('restore').files; $('restore').value = '';
  if (!file) return;
  const count = await restoreBackup(await db, file); await refresh(true); message(() => t("已导入 {0} 份记录；同 ID 的已有记录未覆盖。",count));
});

function disconnect() {
  connection?.abort(); aiRequest?.abort(); connection = undefined; aiRequest = undefined; activeRuntime = undefined;
  $('runtime-key').value = ''; $('model').replaceChildren(localCopy(new Option('', ''), () => t("连接后选择"))); $('model').disabled = true;
  localCopy($('ai-state'), () => t("未连接")); localCopy($('answer'), () => ''); $('answer').hidden = true;
  $('send-ai').disabled = true; $('stop-ai').disabled = true;
}
$('provider').onchange = () => { disconnect(); const lm = $('provider').value === 'lmstudio'; $('runtime-key-label').hidden = !lm; $('port').value = lm ? '1234' : '11434'; };
$('port').oninput = disconnect;
$('runtime-key').oninput = () => {
  if (activeRuntime || connection) {
    const token = $('runtime-key').value;
    disconnect(); $('runtime-key').value = token;
  }
};
$('disconnect').onclick = disconnect;
$('ai-config').onsubmit = event => {
  event.preventDefault();
  const key = $('runtime-key').value;
  disconnect();
  void act(async () => {
    if (!isSecureContext) throw new Error(t("请在 HTTPS 或这台设备的 localhost 打开工作区后再连接 AI。"));
    const client = runtime($('provider').value, Number($('port').value), key);
    const job = connection = new AbortController(), timer = setTimeout(() => job.abort(), 8_000);
    try {
      const models = await client.models(job.signal);
      if (job !== connection) return;
      if (!models.length) throw new Error(t("运行时没有可选的本机模型。请先安装一个本地模型。"));
      activeRuntime = client;
      $('model').replaceChildren(...models.map(name => new Option(name, name)));
      $('model').disabled = false; $('send-ai').disabled = false;
      localCopy($('ai-state'), () => t("已连接 · {0}",client.origin));
    } finally { clearTimeout(timer); if (connection === job) connection = undefined; }
  }, event.submitter);
};
$('stop-ai').onclick = () => aiRequest?.abort();
$('ai-form').onsubmit = event => {
  event.preventDefault();
  if (!activeRuntime || aiRequest || !$('prompt').value.trim()) return;
  const client = activeRuntime, job = aiRequest = new AbortController();
  $('send-ai').disabled = true; $('stop-ai').disabled = false;
  localCopy($('answer'), () => t("本机模型正在处理…")); $('answer').hidden = false;
  void act(async () => {
    const timer = setTimeout(() => job.abort(), 90_000);
    try {
      const output = await client.generate($('model').value, $('prompt').value, job.signal);
      if (aiRequest === job) localCopy($('answer'), () => output);
    } catch (error) {
      if (aiRequest === job) localCopy($('answer'), () => errorText(error));
    } finally {
      clearTimeout(timer);
      if (aiRequest === job) { aiRequest = undefined; $('send-ai').disabled = false; $('stop-ai').disabled = true; }
    }
  });
};

async function shareRequest(path, init = {}) {
  const response = await fetch('/share/' + path, {...init, credentials: 'omit', redirect: 'error', cache: 'no-store'});
  if (response.status === 404) throw new Error(t("这个地址没有启用共享服务，或该题目已下架。"));
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.error || t("共享服务暂时不可用（{0}）。",response.status));
  }
  return response;
}
const authorization = key => ({Authorization: `Bearer ${key}`});
async function loadShared(append = false) {
  if (!sharingReady) {
    const config = await (await shareRequest('config')).json();
    $('share-form').hidden = !config.submissions || !isSecureContext;
    $('moderation').hidden = !isSecureContext;
    sharingReady = true;
  }
  const query = append && cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  const data = await (await shareRequest('papers' + query)).json();
  const rows = data.papers.map(p => row(p.title, mb(p.size), button("保存到私人题库", async () => {
    const file = await (await shareRequest(`papers/${p.id}`)).blob();
    await addPapers(await db, [await newPaper(file, p.title.replace(/[/\\\x00-\x1f]/g, ' ') + '.pdf')]);
    await refresh(true); message(() => t("已下载并保存在当前设备。"));
  })));
  if (!append) $('shared-papers').replaceChildren();
  $('shared-papers').append(...rows);
  cursor = data.cursor;
  $('more-shared').hidden = !cursor;
  localCopy($('shared-status'), () => $('shared-papers').childElementCount ? t("只显示审核通过的 PDF。") : t("暂无已发布题目。"));
}
function refreshShared(append = false, control) {
  void act(async () => {
    try { await loadShared(append); }
    catch (error) { localCopy($('shared-status'), () => errorText(error)); throw error; }
  }, control);
}
$('reload-shared').onclick = () => refreshShared(false, $('reload-shared'));
$('more-shared').onclick = () => refreshShared(true, $('more-shared'));
$('share-form').onsubmit = event => {
  event.preventDefault();
  const [file] = $('share-file').files;
  const title = $('share-title').value.trim(), code = $('share-code').value;
  if (!isSecureContext || !$('share-consent').checked || !file || !title) return;
  void act(async () => {
    if (file.size > 10 * 1048576) throw new Error(t("共享 PDF 上限为 10 MB。"));
    const blob = await pdfBlob(file);
    await shareRequest('submissions', {method: 'POST', body: blob, headers: {...authorization(code), 'Content-Type': 'application/pdf', 'X-Share-Title': encodeURIComponent(title), 'X-Share-Consent': 'confirmed'}});
    $('share-form').reset(); message(() => t("已提交，审核通过前不会出现在共享题库。"));
  }, event.submitter);
};

async function loadReview() {
  const key = reviewKey;
  const data = await (await shareRequest('review', {headers: authorization(key)})).json();
  if (key !== reviewKey) return;
  $('review-papers').replaceChildren(...data.papers.map(p => {
    const action = (label, type) => button(label, async () => {
      if (!confirm(`${t(label)}「${p.title}」？`)) return;
      await shareRequest(`review/${p.id}/${type}`, {method: 'POST', headers: authorization(reviewKey)});
      await loadReview(); await loadShared(); message(() => t("审核结果已保存。"));
    });
    return row(p.title, () => `${p.published ? t("已发布") : t("待审核")} · ${mb(p.size)}`, ...(p.published ? [action("下架", 'remove')] : [
      button("下载审阅", async () => downloadBlob(await (await shareRequest(`review/${p.id}/file`, {headers: authorization(reviewKey)})).blob(), 'Review.pdf')),
      action("通过并发布", 'approve'), action("拒绝", 'reject'),
    ]));
  }));
}
$('review-form').onsubmit = event => {
  event.preventDefault();
  reviewKey = $('review-key').value; $('review-key').value = ''; $('review-papers').replaceChildren();
  void act(loadReview, event.submitter);
};
$('clear-review').onclick = () => { reviewKey = ''; $('review-key').value = ''; $('review-papers').replaceChildren(); };

function showView(control) {
  for (const view of document.querySelectorAll('.view')) view.hidden = view.id !== control.dataset.view;
  for (const nav of document.querySelectorAll('[data-view]')) {
    if (nav === control) nav.setAttribute('aria-current', 'page');
    else nav.removeAttribute('aria-current');
  }
  message('');
  if (control.dataset.view === 'shared') refreshShared();
  if (['library','data','questions'].includes(control.dataset.view)) void act(() => refresh());
}
document.querySelectorAll('[data-view]').forEach(control => control.onclick = () => showView(control));
$('go-search').onclick = () => { showView(document.querySelector('[data-view="questions"]')); $('question-query').focus(); };
function offline() { localCopy($('offline'), () => navigator.onLine ? t("设备端工作区") : t("离线 · 私人题库可用")); }
window.addEventListener('offline', offline); window.addEventListener('online', offline); offline();
if (isSecureContext && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').then(() => navigator.serviceWorker.ready).then(() => {
    localCopy($('offline-detail'), () => t("已缓存当前工作区页面。离线时可打开私人题库；共享题库需要联网。"));
  }).catch(() => {});
}
void act(() => refresh());
