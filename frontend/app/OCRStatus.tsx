'use client';
import {useEffect,useState} from 'react';
import {api} from './api';
type FileStatus={id:string;filename:string;status:string;page:number;total:number;error:string};
export default function OCRStatus(){const [files,setFiles]=useState<FileStatus[]>([]);useEffect(()=>{const refresh=()=>void api<{files:FileStatus[]}>('/api/ocr/status').then(r=>setFiles(r.files)).catch(()=>{});refresh();const timer=setInterval(refresh,2500);return()=>clearInterval(timer);},[]);return files.length?<section className="work-panel" aria-live="polite"><h3>扫描件 OCR · 本机离线</h3>{files.map(f=><div key={f.id}><span>{f.filename} · {f.status==='running'?'正在识别':f.status==='failed'?'识别失败':'已识别'} · 第 {f.page}/{f.total} 页</span>{f.error&&<p role="alert">{f.error}</p>}</div>)}<p>OCR 文字供搜索与拆题使用，数学公式和官方答案请对照原件核对。</p></section>:null;}
