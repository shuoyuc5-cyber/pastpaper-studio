// Served only by the loopback QA fixture server. Runs the real UI with generated documents.
import {fixturePdf, fixtureQuestions, submissionCode, moderationKey} from './share-fixture.mjs';

const mode = new URL(location.href).searchParams.get('qa');
const phase = sessionStorage.getItem('v3-qa-phase');
const $ = selector => document.querySelector(selector);
const state = [];
const report = document.createElement('div');
report.id = 'qa-report'; report.className = 'sr-only'; report.role = 'status';
document.body.append(report);
const pass = value => { state.push(value); report.textContent = 'QA_RUNNING ' + state.join(' | '); };
const finish = () => { sessionStorage.removeItem('v3-qa-phase'); report.textContent = 'QA_PASS ' + state.join(' | '); };
const assert = (value, message) => { if (!value) throw new Error(message); };
async function until(selector, content) {
  const start = performance.now();
  while (performance.now() - start < 8500) {
    const node = $(selector);
    if (node && !node.closest('[hidden]') && (content === undefined || node.textContent.includes(content))) return node;
    await new Promise(resolve => setTimeout(resolve, 35));
  }
  throw new Error(`${selector} did not display ${content || 'the expected control'} (${($(selector)?.textContent || '').slice(0,150)})`);
}
const click = selector => $(selector).click();
const view = name => click(`[data-view="${name}"]`);
const fill = (selector, value) => { const node = $(selector); node.value = value; node.dispatchEvent(new Event('input', {bubbles:true})); };
const status = content => until('#message', content);
const pdf = (name, text) => new File([fixturePdf(text)], name, {type:'application/pdf'});
function selectFiles(selector, ...files) {
  const transfer = new DataTransfer();
  for (const file of files) transfer.items.add(file);
  const node = $(selector); node.files = transfer.files; node.dispatchEvent(new Event('change', {bubbles:true}));
}
async function layout() {
  await until('#count','份 PDF');
  for (const name of ['library','questions','shared','ai','data']) {
    view(name);
    await until(`#${name} h1`);
    assert(document.documentElement.scrollWidth <= innerWidth, `${name} overflows at ${innerWidth}px`);
  }
  view('library');
  $('.skip').focus();
  assert(document.activeElement === $('.skip'), 'skip link cannot receive focus');
  $('.skip').blur();
  pass(`responsive:${innerWidth}px/five views`);
}

const note = 'PRIVATE_NOTE_FIXTURE: probability steps';
const draft = 'PRIVATE_DRAFT_FIXTURE: 3/8';
const prompt = 'LOCAL_PROMPT_FIXTURE: explain probability';
const runtimePort = Number(location.port) + 1;
const seen = [];
const realFetch = globalThis.fetch.bind(globalThis);
if (mode === 'flow' || phase) globalThis.fetch = async (url, init = {}) => {
  const target = new URL(url, location.href);
  const body = typeof init.body === 'string' ? init.body : (init.body instanceof Blob ? await init.body.text() : '');
  seen.push({path: target.pathname, origin: target.origin, method: init.method || 'GET', body, authorization: new Headers(init.headers).get('Authorization')});
  return realFetch(url, init);
};

async function search(query, expected) {
  view('questions'); fill('#question-query', query); click('#find-questions');
  await until('#question-status', `找到 ${expected} 个结果`);
  assert(document.querySelectorAll('#question-results li').length === expected, 'wrong page count');
}

async function cardPreview() {
  await until('#count','0 份 PDF');
  selectFiles('#pdfs', pdf('0580_s26_qp_11.pdf',fixtureQuestions), pdf('0580_s26_ms_11.pdf','Official fixture mark scheme'));
  await status('保存 2 份 PDF');
  fill('#question-subject','0580');
  await search('',3);
  const images = Array.from(document.querySelectorAll('#question-results img'));
  assert(images.length === 6, 'expected two screenshots per question');
  for (const image of images) { image.loading = 'eager'; await image.decode(); }
  assert(document.documentElement.scrollWidth <= innerWidth, 'question cards overflow');
  pass(`visible previews at ${innerWidth}px`);
  finish();
}

async function folderImport(){
  await until('#count','0 份 PDF');
  selectFiles('#folder-pdfs',pdf('folder-fixture.pdf','Synthetic local folder document'),
              new File(['broken'],'bad.pdf'),new File(['ignored'],'notes.txt'));
  await until('#folder-summary','找到 2 份 PDF');
  assert($('#folder-summary').textContent.includes('忽略 1'),'non-PDF filtering failed');
  assert($('#count').textContent.includes('0 份 PDF'),'folder imported before confirmation');
  click('#folder-import');await until('#folder-summary','已导入 1 · 失败 1');
  click('#folder-retry');await until('#folder-summary','已导入 1 · 失败 1');
  await until('#count','1 份 PDF');
  pass('folder preview, ignored file, local import and failed-only retry');finish();
}

async function switchLanguage(){
  await until('#count','0 PDFs');
  selectFiles('#pdfs', pdf('0580_s26_qp_11.pdf',fixtureQuestions));
  await until('#papers li','0580_s26_qp_11.pdf');
  $('#papers li button:last-child').click();
  fill('#notes','Unsaved study note');
  fill('#draft','Unsaved answer');
  selectFiles('#folder-pdfs',pdf('queued.pdf','Synthetic queued PDF'),new File(['ignored'],'notes.txt'));
  await until('#folder-summary','Found 1 PDFs');
  const changeLanguage = value => {
    const select = $('#device-language');
    select.value = value;
    select.dispatchEvent(new Event('change', {bubbles:true}));
  };
  changeLanguage('zh-CN');
  await until('#folder-summary','找到 1 份 PDF');
  assert($('#device-theme').selectedOptions[0].textContent === '跟随系统','appearance labels did not switch');
  changeLanguage('en');
  await until('#folder-summary','Found 1 PDFs');
  assert(document.documentElement.lang === 'en' && $('#notes').value === 'Unsaved study note' &&
         $('#draft').value === 'Unsaved answer' && !$('#editor').hidden,'language switch lost unsaved input');
  assert(!/\p{Script=Han}/u.test($('#library').innerText),'English library still shows Chinese system copy');
  click('#folder-import');
  await until('#papers','queued.pdf');
  pass('device locale follows browser, live EN/ZH/EN switch preserves drafts and queued folder PDFs');
  finish();
}

async function begin() {
  await layout(); await until('#count','0 份 PDF'); pass('fresh profile empty');
  selectFiles('#pdfs', pdf('0580_s26_qp_11.pdf',fixtureQuestions), pdf('0580_s26_ms_11.pdf','Official fixture mark scheme'));
  await status('保存 2 份 PDF');
  assert($('#papers').textContent.match(/已配对/g)?.length === 2, 'QP/MS pairing missing');
  fill('#search','missing needle'); await until('#no-papers');
  fill('#search','0580'); assert(document.querySelectorAll('#papers li').length === 2, 'filename search broken');
  fill('#search','');
  await search('probability',1);
  const card = $('#question-results li');
  assert(card.textContent.includes('Question 1(a)') && card.textContent.includes('Find the probability') && card.textContent.includes('May/June 2026 · Core'), 'question label, stem or source missing');
  const images = Array.from(card.querySelectorAll('img'));
  assert(images.length === 2, 'common stem and question screenshots missing');
  for (const image of images) {
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(image, 0, 0);
    assert(canvas.height < 200 && ctx.getImageData(0, 0, canvas.width, canvas.height).data.some((byte, i) => i % 4 === 0 && byte < 100), 'preview is blank or not cropped');
  }
  const anchorClick = HTMLAnchorElement.prototype.click;
  let opened;
  HTMLAnchorElement.prototype.click = function () { opened = this.href; };
  try {
    click('#question-results button');
    assert(opened?.startsWith('blob:') && opened.endsWith('#page=1'), 'hit must open local PDF at its matching page');
    opened = undefined;
    click('#question-results button:nth-child(2)');
    assert(opened?.startsWith('blob:') && !opened.includes('#page='), 'paired mark scheme should open the original PDF');
  } finally { HTMLAnchorElement.prototype.click = anchorClick; }
  fill('#question-subject','0580'); fill('#question-year','2025'); fill('#question-level','Core');
  await search('',3);
  fill('#question-marks','2'); fill('#question-difficulty','easy');
  await search('',2);
  fill('#question-topic','Probability');
  await search('',1);
  fill('#question-topic',''); fill('#question-marks',''); fill('#question-difficulty','');
  fill('#question-level',''); fill('#question-subject',''); fill('#question-year','');
  await search('no such fixture expression',0);
  view('library'); click('#papers li button:nth-child(2)');
  fill('#notes',note); fill('#draft',draft); click('#editor button.primary');
  await status('学习记录已在当前设备保存');
  assert(!seen.some(r=>r.method!=='GET'), 'private import/search/edit generated a write request');
  sessionStorage.setItem('v3-qa-phase','after-reload');
  pass('import | QP/MS | local filter | text/page search | private note save');
  location.reload();
}

async function afterReload() {
  await until('#count','2 份 PDF');
  click('#papers li button:nth-child(2)');
  assert($('#notes').value === note && $('#draft').value === draft, 'notes/drafts not restored after real reload');
  pass(`responsive:${innerWidth}px/five views | fresh profile | import/QP-MS | keyword/topic/subject/level/year/marks/difficulty | cropped previews and original links | note/draft reload`);
  let archived;
  const createObjectURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = blob => { if (blob.type === 'application/octet-stream') archived = blob; return createObjectURL(blob); };
  view('data'); click('#export');
  for (let i=0; !archived && i<120; i++) await new Promise(resolve=>setTimeout(resolve,35));
  URL.createObjectURL = createObjectURL;
  assert(archived?.size > 100,'missing backup download');
  let confirmations = 0;
  window.confirm = () => { confirmations++; return true; };
  view('library'); click('#papers li button:nth-child(2)'); click('#remove-paper'); await status('已移除本地副本');
  await until('#count','1 份 PDF'); view('data');
  selectFiles('#restore',new File([archived],'fixture.ppstudio'));
  await status('已导入 1 份记录');
  selectFiles('#restore',new File([archived],'fixture.ppstudio'));
  await status('已导入 0 份记录');
  selectFiles('#restore',new File(['bad'],'bad.ppstudio'));
  await status('备份格式无效'); pass('download backup | delete | merge/restore | invalid backup');

  view('ai'); fill('#port',String(runtimePort)); click('#ai-config button.primary');
  await until('#ai-state','已连接'); assert($('#model').options.length===1,'cloud model was not filtered');
  fill('#prompt',prompt); click('#send-ai'); await until('#answer','Mock local response');
  $('#provider').value='lmstudio'; $('#provider').dispatchEvent(new Event('change',{bubbles:true}));
  fill('#port',String(runtimePort)); click('#ai-config button.primary'); await status('拒绝授权');
  fill('#runtime-key','fixture-runtime-token'); click('#ai-config button.primary'); await until('#ai-state','已连接');
  click('#disconnect'); assert(!$('#runtime-key').value && $('#send-ai').disabled,'disconnect did not clear authorization');
  pass('Ollama request | LM Studio 401 and reconnect | disconnect');

  view('shared'); await until('#share-form');
  fill('#share-title','Synthetic QA public question'); fill('#share-code',submissionCode);
  selectFiles('#share-file',pdf('public-fixture.pdf',`Shared question ${Date.now()}`));
  click('#share-form button');
  assert(!seen.some(r=>r.path==='/share/submissions'),'unchecked share consent was bypassed');
  $('#share-consent').checked=true; click('#share-form button'); await status('已提交');
  assert(!$('#shared-papers').textContent.includes('Synthetic QA public question'),'pending file visible');
  $('#moderation').open=true; fill('#review-key',moderationKey); click('#review-form button');
  await until('#review-papers','通过并发布');
  const own = () => Array.from(document.querySelectorAll('#review-papers li')).find(row=>row.textContent.includes('Synthetic QA public question'));
  const reviewAction = label => Array.from(own().querySelectorAll('button')).find(button=>button.textContent===label).click();
  reviewAction('通过并发布'); await status('审核结果已保存');
  await until('#shared-papers','Synthetic QA public question');
  const published = Array.from(document.querySelectorAll('#shared-papers li')).find(row=>row.textContent.includes('Synthetic QA public question'));
  published.querySelector('button').click(); await status('已下载并保存在当前设备');
  reviewAction('下架'); await status('审核结果已保存');
  assert(!$('#shared-papers').textContent.includes('Synthetic QA public question') && confirmations>=3,'takedown or confirmation failed');
  await search('Shared question',1);
  const fullPage = $('#question-results img');
  assert($('#question-results').textContent.includes('原页预览') && fullPage, 'unknown layouts must show the original page');
  await fullPage.decode();
  const ownHost = seen.filter(r=>r.origin===location.origin);
  assert(!ownHost.some(r=>r.path.startsWith('/api/') || r.body.includes(note) || r.body.includes(draft) || r.body.includes(prompt) || r.authorization?.includes('fixture-runtime-token')), 'private content or AI credentials reached the site');
  const promptCalls = seen.filter(r=>r.body.includes(prompt));
  assert(promptCalls.length===1 && promptCalls[0].origin===`http://127.0.0.1:${runtimePort}` && promptCalls[0].path==='/api/generate','prompt was not isolated to loopback');
  assert(ownHost.filter(r=>r.path==='/share/submissions'&&r.method==='POST').length===1,'unexpected number of share uploads');
  pass('sharing consent | pending/review/publish/save/takedown | browser network boundaries');

  await navigator.serviceWorker.ready;
  for (let i=0; !navigator.serviceWorker.controller && i<100; i++) await new Promise(resolve=>setTimeout(resolve,30));
  assert(navigator.serviceWorker.controller,'offline worker did not take control');
  // Exercise the same lazy cache path a second online search would take.
  await fetch('/device/pdf-engine/pdf.min.mjs'); await fetch('/device/pdf-engine/pdf.worker.min.mjs');
  assert(await caches.match('/device/pdf-engine/pdf.min.mjs'),'PDF engine not cached after online use');
  sessionStorage.setItem('v3-qa-stage',JSON.stringify(state)); sessionStorage.setItem('v3-qa-phase','offline');
  await fetch('/__qa/disconnect',{method:'POST'}); location.replace('/device/index.html');
}

async function offline() {
  state.push(...JSON.parse(sessionStorage.getItem('v3-qa-stage') || '[]'));
  await until('#count','3 份 PDF'); await search('probability',1);
  const response = await fetch('/__qa/reconnect',{method:'POST'});
  assert((await response.json()).droppedDeviceReads >= 3,'preview did not simulate network loss');
  sessionStorage.removeItem('v3-qa-stage'); pass('real cached reload and PDF search with network reads dropped'); finish();
}

if (mode || phase) void (async () => {
  try {
    if (phase==='offline') await offline();
    else if (mode==='layout') { await layout(); finish(); }
    else if (mode==='cards') await cardPreview();
    else if (mode==='folder') await folderImport();
    else if (mode==='language') await switchLanguage();
    else if (mode==='flow' && phase==='after-reload') await afterReload();
    else if (mode==='flow') await begin();
  } catch (error) {
    if (phase==='offline') await realFetch('/__qa/reconnect',{method:'POST'}).catch(()=>{});
    sessionStorage.removeItem('v3-qa-phase');
    report.textContent = `QA_FAIL ${error.message} | ${state.join(' | ')}`;
  }
})();
