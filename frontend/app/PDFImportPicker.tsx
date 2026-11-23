'use client';
import {useStudioText,useStudioStatus} from "./preferences";

import {useEffect, useRef, useState} from 'react';

type Receipt = {id:string;status:string;error:string|null};
type Entry = {key:number;file:File;path:string;selected:boolean;state:string;id?:string;error?:string};
const pending = (state:string) => state==='waiting'||state==='processing';
const finished = (state:string) => ['completed','needs_review','duplicate','failed','missing','deleted','cancelled'].includes(state);
const labels:Record<string,string> = {
  ready:'待导入', sending:'上传中', waiting:'等待识别', processing:'识别中', completed:'已导入',
  needs_review:'已导入，待核对', duplicate:'已存在相同内容', failed:'导入失败', missing:'文件已移走', deleted:'文件已删除', cancelled:'已取消',
};
const delay = (ms:number) => new Promise(resolve=>setTimeout(resolve,ms));

export function usePDFImports() {
  const tr=useStudioText();

  const [entries,setEntries] = useState<Entry[]>([]);
  const [ignored,setIgnored] = useState(0);
  const [active,setActive] = useState(false);
  const [pollError,setPollError] = useState(false);
  const activeRef = useRef(false);
  const nextKey = useRef(0);
  const waiting = entries.filter(entry=>entry.id&&pending(entry.state)).map(entry=>entry.id!).join(',');
  useEffect(()=>{
    if(!waiting)return;
    const ids=waiting.split(',');
    const controller=new AbortController();
    let running=false;
    async function poll(){

      if(running)return;
      running=true;
      try{
        const all=new Map<string,Receipt>();
        for(let i=0;i<ids.length;i+=50){
          const params=new URLSearchParams(ids.slice(i,i+50).map(id=>['ids',id]));
          const response=await fetch('/api/import/status?'+params,{cache:'no-store',signal:controller.signal});
          if(!response.ok)throw new Error();
          const data: {files:Receipt[]} = await response.json();
          for(const record of data.files)all.set(record.id,record);
        }
        if(controller.signal.aborted)return;
        setPollError(false);
        setEntries(rows=>rows.map(row=>{
          const record=row.id&&all.get(row.id);
          return record&&pending(row.state)?{...row,state:record.status,error:record.error||undefined}:row;
        }));
      }catch{if(!controller.signal.aborted)setPollError(true);}
      finally{running=false;}
    }
    const timer=setInterval(()=>void poll(),1800);
    void poll();
    return()=>{controller.abort();clearInterval(timer);};
  },[waiting]);

  function choose(files:File[]) {

    if(activeRef.current||!files.length)return;
    const pdfs=files.filter(file=>file.name.toLowerCase().endsWith('.pdf'));
    setIgnored(files.length-pdfs.length);
    setPollError(false);
    setEntries(pdfs.map(file=>({key:++nextKey.current,file,path:file.webkitRelativePath||file.name,selected:true,state:'ready'})));
  }
  function select(key:number,selected:boolean){
setEntries(rows=>rows.map(row=>row.key===key?{...row,selected}:row));}
  async function run(retry=false){

    if(activeRef.current)return;
    const queue=entries.filter(row=>retry?['failed','missing','deleted','cancelled'].includes(row.state):row.selected&&row.state==='ready');
    if(!queue.length)return;
    activeRef.current=true;setActive(true);setPollError(false);
    function update(key:number,change:Partial<Entry>){

      setEntries(rows=>rows.map(row=>row.key===key?{...row,...change}:row));
    }
    try{
      for(const row of queue){
        update(row.key,{state:'sending',error:undefined,id:undefined});
        try{
          if(row.file.size>40*1024*1024)throw new Error(tr("单个 PDF 不能超过 40 MB。"));
          const params=new URLSearchParams({filename:row.file.name});
          if(row.file.webkitRelativePath)params.set('relative_path',row.file.webkitRelativePath);
          const send=()=>fetch('/api/import/upload?'+params,{method:'POST',body:row.file});
          let response=await send();
          if(response.status===429){
            update(row.key,{error:tr("等待导入限额恢复…")});
            await delay(60_000);
            response=await send();
          }
          const result=await response.json().catch(()=>null);
          if(!response.ok||!result?.id)throw new Error(typeof result?.detail==='string'?result.detail:tr("导入未完成（{0}）",response.status));
          update(row.key,{state:result.status,id:result.id,error:result.error||undefined});
        }catch(error){update(row.key,{state:'failed',error:error instanceof Error?error.message:tr("导入未完成")});}
      }
    }finally{activeRef.current=false;setActive(false);}
  }

  async function cancel(entry:Entry){
    if(!entry.id||entry.state!=='waiting')return;
    const response=await fetch('/api/import/'+encodeURIComponent(entry.id)+'/cancel',{method:'POST'});
    if(!response.ok){
      setEntries(rows=>rows.map(row=>row.key===entry.key?{...row,error:tr("只能取消尚未开始的导入")}:row));
    }else{
      setEntries(rows=>rows.map(row=>row.key===entry.key?{...row,state:'cancelled',error:undefined}:row));
    }
  }

  return {entries,ignored,active,pollError,choose,select,run,cancel};
}

export default function PDFImportPicker({uploader,disabled=false,publicMode=false}:{uploader:ReturnType<typeof usePDFImports>;disabled?:boolean;publicMode?:boolean}){
  const tr=useStudioText();
  const statusCopy=useStudioStatus();

  const folder=useRef<HTMLInputElement>(null),single=useRef<HTMLInputElement>(null);
  const {entries,ignored,active,pollError,choose,select,run,cancel}=uploader;
  const ready=entries.filter(row=>row.selected&&row.state==='ready').length;
  const imported=entries.filter(row=>row.state==='completed'||row.state==='needs_review').length;
  const failures=entries.filter(row=>['failed','missing','deleted','cancelled'].includes(row.state)).length;
  const duplicates=entries.filter(row=>row.state==='duplicate').length;
  const processed=entries.filter(row=>finished(row.state)).length;
  const pendingCount=entries.filter(row=>pending(row.state)).length;
  const started=entries.some(row=>row.state!=='ready');
  return <div className="pdf-import-picker">
    <div className="folder-controls">
      <input hidden type="file" multiple aria-label={tr("选择 PDF 文件夹")} ref={node=>{folder.current=node;node?.setAttribute('webkitdirectory','');}}
        onChange={event=>{choose(Array.from(event.currentTarget.files||[]));event.currentTarget.value='';}}/>
      <input hidden type="file" accept=".pdf,application/pdf" aria-label={tr("选择单个 PDF")} ref={single}
        onChange={event=>{choose(Array.from(event.currentTarget.files||[]));event.currentTarget.value='';}}/>
      <button className="button primary-button" type="button" disabled={active||disabled} onClick={()=>folder.current?.click()}>{tr("选择文件夹")}</button>
      <button className="button" type="button" disabled={active||disabled} onClick={()=>single.current?.click()}>{tr("选择单个 PDF")}</button>
    </div>
    {!!ignored&&<p role="status">{tr("已忽略")+" "}{ignored}{" "+tr("个非 PDF 文件。")}</p>}
    {!!entries.length&&<div className="pdf-import-review">
      <h3>{tr("确认要导入的 PDF ·")+" "}{entries.length}{" "+tr("份")}</h3>
      <ul aria-label={tr("待导入 PDF")}>
        {entries.map(row=><li key={row.key}>
          <label><input type="checkbox" checked={row.selected} disabled={active||row.state!=='ready'} onChange={e=>select(row.key,e.target.checked)}/>
          <span>{row.path}</span></label>
          <span>{tr(labels[row.state]||row.state)}{row.error&&<small>{statusCopy(row.error)}</small>}{publicMode&&row.state==='waiting'&&<button type="button" onClick={()=>void cancel(row)}>{tr("取消排队")}</button>}</span>
        </li>)}
      </ul>
      <div className="folder-controls">
        {!!ready&&<button className="button primary-button" type="button" disabled={active||disabled} onClick={()=>void run()}>{tr("导入所选 PDF ·")+" "}{ready}{" "+tr("份")}</button>}
        {!!failures&&<button className="button" type="button" disabled={active||disabled} onClick={()=>void run(true)}>{tr("重试失败文件 ·")+" "}{failures}{" "+tr("份")}</button>}
      </div>
      {started&&<div className="pdf-import-status" role="status">
        <progress aria-label={tr("PDF 导入进度")} value={processed} max={Math.max(1,entries.filter(row=>row.selected||row.state!=='ready').length)}/>
        <span>{tr("已导入")+" "}{imported}{" "+tr("· 重复")+" "}{duplicates}{" "+tr("· 失败")+" "}{failures}{pendingCount? tr(" · 待识别 {0}",pendingCount):''}{active?tr("· 正在上传"):''}</span>
      </div>}
      {pollError&&<p role="alert">{tr("无法读取识别进度，连接恢复后会自动更新。")}</p>}
    </div>}
  </div>;
}
