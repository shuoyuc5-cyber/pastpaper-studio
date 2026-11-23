'use client';
import {useStudioText,useStudioStatus} from "./preferences";
import {useEffect,useState} from 'react';
import {api} from './api';
type FileStatus={id:string;filename:string;status:string;page:number;total:number;error:string};
export default function OCRStatus(){
  const tr=useStudioText();
  const statusCopy=useStudioStatus();
const [files,setFiles]=useState<FileStatus[]>([]);useEffect(()=>{const refresh=()=>void api<{files:FileStatus[]}>('/api/ocr/status').then(r=>setFiles(r.files)).catch(()=>{});refresh();const timer=setInterval(refresh,2500);return()=>clearInterval(timer);},[]);return files.length?<section className="work-panel" aria-live="polite"><h3>{tr("扫描件 OCR · 本机离线")}</h3>{files.map(f=><div key={f.id}><span>{f.filename} · {f.status==='running'?tr("正在识别"):f.status==='failed'?tr("识别失败"):tr("已识别")}{" "+tr("· 第")+" "}{f.page}/{f.total}{" "+tr("页")}</span>{f.error&&<p role="alert">{statusCopy(f.error||'')}</p>}</div>)}<p>{tr("OCR 文字供搜索与拆题使用，数学公式和官方答案请对照原件核对。")}</p></section>:null;}
