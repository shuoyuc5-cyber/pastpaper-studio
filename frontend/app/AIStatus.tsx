'use client';

import {useEffect,useState} from 'react';
import {api,jsonBody,type AIConfig} from './api';

export default function AIStatus({english=false}: {english?:boolean}) {
  const [config,setConfig]=useState<AIConfig|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    const refresh=()=>void api<AIConfig>('/api/ai/settings').then(setConfig).catch(()=>{});
    refresh();
    window.addEventListener('studio-ai-settings',refresh);
    return()=>window.removeEventListener('studio-ai-settings',refresh);
  },[]);
  const t=(en:string,zh:string)=>english?en:zh;
  const status=(allowed?:boolean, enabled?:boolean)=>!allowed?t('Disabled by admin','管理员已禁用'):
    enabled?t('On · Turn off','已开启 · 关闭'):t('Off','已关闭');
  const errorMessage=error&&(english?'Could not update AI settings.':error);

  return <>
    <button className="ai-status" disabled={!config?.local_allowed} title={errorMessage||t('Local Ollama toggle','本地 Ollama 开关')} onClick={()=>{
      if(config)void api('/api/ai/settings',jsonBody({...config,local_enabled:!config.local_enabled},'PUT'))
        .then(()=>{setConfig({...config,local_enabled:!config.local_enabled});window.dispatchEvent(new Event('studio-ai-settings'));})
        .catch(e=>setError(e.message));
    }}>{t('Local AI','本地 AI')} · {status(config?.local_allowed,config?.local_enabled)}</button>
    <button className="ai-status" title={config?.cloud_enabled?t('Turn off ChatGPT and stop its tasks','点击关闭云端并停止任务'):t('Connect ChatGPT in Settings','在设置中连接 ChatGPT，选择模型后手动开启')} onClick={()=>{
      if(config?.cloud_enabled)void api('/api/chatgpt/settings',jsonBody({enabled:false},'PUT'))
        .then(()=>window.dispatchEvent(new Event('studio-ai-settings'))).catch(e=>setError(e.message));
    }}><span className="ai-dot"/>ChatGPT <b>{status(config?.cloud_allowed,config?.cloud_enabled)}</b></button>
  </>;
}
