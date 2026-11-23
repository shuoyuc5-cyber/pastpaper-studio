'use client';

import {useEffect,useRef,useState} from 'react';
import {api,jsonBody} from './api';
import {useStudioText,useStudioStatus,useStudioPreferences} from './preferences';

type Copy = {id:string;filename:string;path:string;added_at:string;can_clean:boolean};
type Group = {id:string;size:number;copies:Copy[]};
type Cleanup = {id:string;error:string|null};
const PAGE_SIZE = 40;
const BATCH_SIZE = 24;

export default function DuplicateManager({onClose,onChanged}:{onClose:()=>void;onChanged:()=>Promise<void>}) {
  const {lang}=useStudioPreferences();
  const tr=useStudioText(), statusCopy=useStudioStatus();
  const dialog=useRef<HTMLDialogElement>(null);
  const [groups,setGroups]=useState<Group[]>([]);
  const [loading,setLoading]=useState(true), [active,setActive]=useState(false);
  const [confirm,setConfirm]=useState<string|null>(null), [error,setError]=useState('');
  const [issues,setIssues]=useState<Record<string,string>>({});
  const [progress,setProgress]=useState<{processed:number;total:number;cleaned:number}|null>(null);
  const [page,setPage]=useState(0);
  const removable=groups.flatMap(group=>group.copies.filter(copy=>copy.can_clean));
  const totalFiles=groups.reduce((total,group)=>total+group.copies.length,0);
  const pageCount=Math.max(1,Math.ceil(groups.length/PAGE_SIZE));
  const currentPage=Math.min(page,pageCount-1);

  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    return()=>element?.close();
  },[]);

  useEffect(()=>{
    const controller=new AbortController();
    let running=false;
    async function load(){
      if(running)return;
      running=true;
      try{
        const result=await api<{groups:Group[]}>('/api/admin/duplicates',{signal:controller.signal});
        if(!controller.signal.aborted){setGroups(result.groups);setError('');void onChanged();}
      }catch(cause){
        if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:'读取失败');
      }finally{
        running=false;
        if(!controller.signal.aborted)setLoading(false);
      }
    }
    if(!active)void load();
    const timer=active?undefined:window.setInterval(()=>void load(),10000);
    return()=>{controller.abort();window.clearInterval(timer);};
  },[active]);

  async function clean(ids:string[]) {
    setActive(true);setConfirm(null);setError('');
    setIssues(previous=>Object.fromEntries(Object.entries(previous).filter(([id])=>!ids.includes(id))));
    let processed=0, cleaned=0;
    setProgress({processed,total:ids.length,cleaned});
    try{
      for(let start=0;start<ids.length;start+=BATCH_SIZE){
        const {results}=await api<{results:Cleanup[]}>('/api/admin/duplicates/clean',jsonBody({ids:ids.slice(start,start+BATCH_SIZE)}));
        const removed=new Set(results.filter(result=>result.error===null).map(result=>result.id));
        const failed=Object.fromEntries(results.flatMap(({id,error})=>error===null?[]:[[id,error]]));
        processed+=results.length;cleaned+=removed.size;
        setGroups(previous=>previous.map(group=>({...group,copies:group.copies.filter(file=>!removed.has(file.id))}))
          .filter(group=>group.copies.length>1));
        setIssues(previous=>({...previous,...failed}));
        setProgress({processed,total:ids.length,cleaned});
      }
    }catch(cause){
      setError(cause instanceof Error?cause.message:'清理失败');
    }finally{
      setActive(false);
      await onChanged();
    }
  }

  const target=removable.find(file=>file.id===confirm);
  const confirmedIds=confirm==='all'?removable.map(file=>file.id):target?[target.id]:[];
  return <dialog ref={dialog} className="question-dialog duplicate-manager" aria-labelledby="duplicate-title"
    onCancel={event=>{event.preventDefault();if(!active)onClose();}}>
    <header><h2 id="duplicate-title">{tr("重复文件")}</h2>
      <button type="button" disabled={active} onClick={onClose}>{tr("关闭")}</button>
    </header>
    <p className="duplicate-totals">{tr("{0} 组 · 共 {1} 个匹配文件",groups.length,totalFiles)}</p>
    <p>{tr("仅管理员可以清理。重复副本移入本机回收区；清理前会确认仍有内容相同的已导入原件。")}</p>
    <div className="work-actions">
      <button type="button" className="studio-primary" disabled={loading||active||!removable.length} onClick={()=>setConfirm('all')}>
        {tr("一键删除所有重复文件")}
      </button>
    </div>
    {confirmedIds.length>0&&<section className="duplicate-confirm work-panel">
      <p>{confirm==='all'?tr("确认清理全部 {0} 个副本？",removable.length):tr("确认清理 {0} 的这个副本？",target?.filename)}</p>
      <div className="work-actions">
        <button type="button" className="studio-primary" onClick={()=>void clean(confirmedIds)}>{tr("确认清理")}</button>
        <button type="button" onClick={()=>setConfirm(null)}>{tr("取消")}</button>
      </div>
    </section>}
    {progress&&<div className="duplicate-progress" role="status">
      <progress max={progress.total} value={progress.processed}/>
      <span>{tr("已检查 {0} / {1} · 已清理 {2} · 未能清理 {3}",progress.processed,progress.total,progress.cleaned,progress.processed-progress.cleaned)}</span>
    </div>}
    {error&&<p className="folder-error" role="alert">{statusCopy(error)}</p>}
    {loading?<p role="status">{tr("正在读取重复文件…")}</p>:!groups.length&&!error?<p>{tr("未找到重复文件。")}</p>:null}
    <div className="duplicate-groups">
      {groups.slice(currentPage*PAGE_SIZE,(currentPage+1)*PAGE_SIZE).map(group=><section key={group.id} className="duplicate-group">
        <header>
          <strong>{group.copies[0].filename}</strong>
          <span className="role-pill">{tr("{0} 个匹配文件",group.copies.length)}</span>
          <small>{new Intl.NumberFormat(lang,{maximumFractionDigits:1}).format(group.size/1024)} KB {tr("每份")}</small>
        </header>
        <ul className="duplicate-list">
          {group.copies.map(file=><li key={file.id}>
            <div className="duplicate-file">
              <strong>{file.filename}</strong>
              <small>{file.added_at&&!Number.isNaN(Date.parse(file.added_at))
                ?tr("导入于 {0}",new Intl.DateTimeFormat(lang,{dateStyle:'medium'}).format(new Date(file.added_at))):tr("导入日期未知")}</small>
              <details><summary>{tr("查看副本路径")}</summary><code>{file.path}</code></details>
              {issues[file.id]&&<small className="folder-error">{statusCopy(issues[file.id])}</small>}
            </div>
            {file.can_clean?<button type="button" disabled={active} onClick={()=>setConfirm(file.id)}>{tr("删除重复文件")}</button>:
              <span className="role-pill">{tr("保留")}</span>}
          </li>)}
        </ul>
      </section>)}
    </div>
    {pageCount>1&&<nav className="work-actions duplicate-pages" aria-label={tr("重复文件分页")}>
      <button type="button" disabled={!currentPage} onClick={()=>setPage(currentPage-1)}>{tr("上一页")}</button>
      <span>{currentPage+1} / {pageCount}</span>
      <button type="button" disabled={currentPage+1>=pageCount} onClick={()=>setPage(currentPage+1)}>{tr("下一页")}</button>
    </nav>}
  </dialog>;
}
