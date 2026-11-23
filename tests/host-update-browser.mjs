import {fixturePdf} from './share-fixture.mjs';

const report=document.createElement('p');
report.id='host-qa-report';report.role='status';document.body.append(report);
const $=selector=>document.querySelector(selector);
const must=(test,message)=>{if(!test)throw new Error(message);};
async function until(test,message){
  const start=Date.now();
  while(Date.now()-start<17_000){if(test())return;await new Promise(resolve=>setTimeout(resolve,40));}
  throw new Error(message);
}
function make(name,relative,content){
  const file=new File([content],name);
  Object.defineProperty(file,'webkitRelativePath',{value:relative});
  return file;
}
try {
  await until(()=>$('.pdf-import-picker input[webkitdirectory]'),'folder picker did not appear');
  const transfer=new DataTransfer();
  transfer.items.add(make('0580_s26_qp_12.pdf','Fixture/Questions/0580_s26_qp_12.pdf',fixturePdf('Synthetic original question 12')));
  transfer.items.add(make('0580_s26_ms_12.pdf','Fixture/Answers/0580_s26_ms_12.pdf',fixturePdf('Synthetic official scheme 12')));
  transfer.items.add(make('broken.pdf','Fixture/Answers/broken.pdf','not a PDF'));
  transfer.items.add(make('notes.txt','Fixture/notes.txt','ignored'));
  const picker=$('.pdf-import-picker input[webkitdirectory]');
  picker.files=transfer.files;picker.dispatchEvent(new Event('change',{bubbles:true}));
  await until(()=>document.querySelectorAll('.pdf-import-review li').length===3,'expected three PDF preview rows');
  must($('.pdf-import-picker').textContent.includes('已忽略 1 个非 PDF 文件'),'unsupported file was not ignored');
  must(!$('.pdf-import-status'),'upload started before confirmation');
  $('.pdf-import-review .primary-button').click();
  await until(()=>$('.pdf-import-status')?.textContent.includes('已导入 2 · 重复 0 · 失败 1'),'successful and failed statuses missing');
  const retry=[...document.querySelectorAll('.pdf-import-review button')].find(button=>button.textContent.includes('重试失败文件'));
  must(retry,'retry is missing');
  retry.click();
  await until(()=>!retry.disabled&&$('.pdf-import-status')?.textContent.includes('已导入 2 · 重复 0 · 失败 1'),'retry changed the successful entries');
  report.textContent='HOST_FOLDER_PASS: preview, nested paths, ignored non-PDF, explicit confirmation, two successful scans, one failure and retry';
}catch(error){report.textContent='HOST_FOLDER_FAIL: '+error.message;}
