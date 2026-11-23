'use client';
import {useStudioText,useStudioStatus} from "./preferences";

import {type FormEvent, type ReactNode, useEffect, useState} from 'react';
import {api, jsonBody, type User} from './api';
import {validEmail} from './email';
import {PreferenceControls} from './preferences';

export default function AuthGate({children}: {children:(user:User,logout:()=>Promise<void>)=>ReactNode}) {
  const tr=useStudioText();
  const statusCopy=useStudioStatus();

  const [user,setUser] = useState<User|null>(null);
  const [setup,setSetup] = useState(false);
  const [needsHost,setNeedsHost] = useState(false);
  const [localHost,setLocalHost] = useState(false);
  const [guestWrites,setGuestWrites] = useState(false);
  const [register,setRegister] = useState(false);
  const [legacy,setLegacy] = useState(false);
  const [loading,setLoading] = useState(true);
  const [email,setEmail] = useState('');
  const [username,setUsername] = useState('');
  const [password,setPassword] = useState('');
  const [showPassword,setShowPassword] = useState(false);
  const [inviteCode,setInviteCode] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [unencrypted,setUnencrypted] = useState(false);
  const [publicSite,setPublicSite] = useState(false);
  const [accountLink,setAccountLink] = useState('');
  const [forgot,setForgot] = useState(false);
  const [notice,setNotice] = useState('');
  const [otp,setOtp] = useState('');
  const [needOtp,setNeedOtp] = useState(false);

  async function refresh() {

    try {
      const data = await api<{user:User|null;setup:boolean;can_setup:boolean;guest_writes:boolean;local_host:boolean;public_mode?:boolean}>('/api/auth/me');
      setPublicSite(Boolean(data.public_mode));
      setUser(data.user ? {...data.user, publicMode:Boolean(data.public_mode)} : null); setSetup(data.can_setup); setRegister(data.can_setup);
      setNeedsHost(data.setup&&!data.can_setup); setLocalHost(data.local_host); setGuestWrites(data.guest_writes);
      setError('');
    } catch (e) { setError(e instanceof Error ? e.message : tr("本地服务未连接")); }
    finally { setLoading(false); }
  }
  useEffect(()=>{
    const token=window.location.hash.match(/^#account=([A-Za-z0-9_-]{43})$/)?.[1];
    if(token){setAccountLink(token);window.history.replaceState(null,'',window.location.pathname);}
    setUnencrypted(window.location.protocol==='http:');void refresh();
  },[]);
  const userId=user?.id;
  useEffect(()=>{
    if(!userId)return;
    let active=true;
    const check=()=>void api<{user:User|null}>('/api/auth/me').then(data=>{
      if(active)setUser(data.user ? {...data.user, publicMode:publicSite} : null);
    }).catch(()=>{});
    const timer=window.setInterval(check,5000);
    window.addEventListener('focus',check);
    return ()=>{active=false;window.clearInterval(timer);window.removeEventListener('focus',check);};
  },[userId,publicSite]);

  async function submit(event: FormEvent) {

    event.preventDefault(); setError(''); setNotice('');
    if (!accountLink&&!legacy&&!validEmail(email)) {setError(tr("请输入有效的电子邮箱地址。"));return;}
    setBusy(true);
    try {
      if(publicSite&&accountLink){
        await api('/api/auth/complete-link',jsonBody({token:accountLink,password}));
        setAccountLink('');setUser(null);setPassword('');
        setNotice(tr("密码已保存，请登录。"));return;
      }
      if(publicSite&&(forgot||register)){
        await api(forgot?'/api/auth/forgot-password':'/api/auth/public-register',
          jsonBody(forgot?{email}:{email,username,invite_code:inviteCode}));
        setForgot(false);setRegister(false);
        setNotice(tr("如果请求符合条件，请查收邮件。"));return;
      }
      const identity = legacy ? {username} : {email:email.trim(),...(register?{username}:{})};
      const data = await api<{user:User}>(`/api/auth/${register?'register':'login'}`, jsonBody({...identity,password,...(needOtp?{otp}:{}),...(register?{invite_code:inviteCode}:{})}));
      setUser({...data.user,publicMode:publicSite}); setOtp('');setNeedOtp(false); setPassword(''); setShowPassword(false);
    } catch (e) {
      if(publicSite&&e instanceof Error&&e.message==='Enter the code from your authenticator.')setNeedOtp(true);
      else setError(e instanceof Error ? e.message : tr("登录失败"));
    }
    finally { setBusy(false); }
  }
  async function logout() {

    try {await api('/api/auth/logout',jsonBody({}));}
    finally {setUser(null);setPassword('');setShowPassword(false);setRegister(false);setLegacy(false);}
  }
  if (user&&(!publicSite||!accountLink)) return children(user,logout);
  const requestLink=publicSite&&(forgot||register);

  return <main className="auth-screen"><div className={`auth-layout${localHost?'':' client-auth-layout'}`}>
    <PreferenceControls/>
    {localHost&&<section className="device-entry" aria-labelledby="device-entry-title">
      <div className="brand-mark"><span>p</span></div><p>PastPaper Studio</p><h1 id="device-entry-title">{tr("设备端工作区")}</h1>
      <p>{tr("私人 PDF、笔记和练习草稿保存在你当前的浏览器。你也可以连接自己的本机 AI。")}</p>
      <a className="button primary-button" href="/device/index.html">{tr("打开设备端工作区")}</a>
    </section>}
    <section className="auth-card">
      <h2>{loading?tr("正在连接本地服务…"):setup?tr("创建主机管理员"):publicSite&&accountLink?tr("设置新密码"):publicSite&&forgot?tr("忘记密码？"):register?tr("添加学习账号"):localHost?tr("登录主机题库"):tr("登录 PastPaper Studio")}</h2>
      <p>{localHost?tr("使用你的主机账号。"):tr("请使用管理员登记的电子邮箱地址和密码。")}</p>
      {unencrypted&&!localHost&&<p className="lan-notice">{tr("局域网连接未加密。请使用可信 Wi-Fi 和此网站专用密码。")}</p>}
      {needsHost&&<p role="status">{publicSite?tr("此站点的管理员账号尚未设置。"):tr("请在运行网站的设备上通过 localhost 创建首个管理员。")}</p>}
      {!loading&&!needsHost&&<form onSubmit={e=>void submit(e)}>
        {!accountLink&&!legacy&&<label>{tr("电子邮箱地址")}<input type="email" autoComplete="username" maxLength={254} value={email} onChange={e=>setEmail(e.target.value)} required/></label>}
        {!accountLink&&(legacy||register)&&<label>{legacy?tr("原有用户名"):tr("用户名")}<input autoComplete={legacy?'username':'nickname'} minLength={2} maxLength={40} value={username} onChange={e=>setUsername(e.target.value)} required/></label>}
        {!requestLink&&<div className="auth-password">
          <label>{tr("密码")}<input type={showPassword?'text':'password'} autoComplete={register||accountLink?'new-password':'current-password'} minLength={accountLink?12:register?8:undefined} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} required/></label>
          <button type="button" className="button" onClick={()=>setShowPassword(!showPassword)}>{showPassword?tr("隐藏密码"):tr("显示密码")}</button>
        </div>}
        {needOtp&&!requestLink&&!accountLink&&<label>{tr("验证器验证码")}<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={otp} onChange={e=>setOtp(e.target.value)} required/></label>}
        {register&&!setup&&<label>{tr("管理员邀请码")}<input value={inviteCode} onChange={e=>setInviteCode(e.target.value)} autoComplete="off" maxLength={128} required/></label>}
        {register&&!publicSite&&<small>{tr("密码至少 8 位。")}</small>}
        <button className="button primary-button" disabled={busy}>{busy?tr("请稍候…"):accountLink?tr("保存新密码"):requestLink?tr("发送邮件"):register?tr("创建账号并进入"):tr("登录")}</button>
      </form>}
      {notice&&<p role="status">{notice}</p>}
      {error&&<p className="folder-error" role="alert">{statusCopy(error)}</p>}
      {localHost&&!loading&&(!register||setup)&&<button type="button" className="text-button" disabled={busy} onClick={()=>{setLegacy(!legacy);setError('');}}>{legacy?tr("使用电子邮箱"):setup?tr("暂用用户名创建管理员"):tr("在本机使用原有用户名")}</button>}
      {guestWrites&&!setup&&!loading&&!accountLink&&!forgot&&<button type="button" className="text-button" onClick={()=>{setRegister(!register);setLegacy(false);setNeedOtp(false);setError('');}}>{register?tr("已有账号，返回登录"):tr("创建学习账号")}</button>}
      {publicSite&&!loading&&!accountLink&&!register&&<button type="button" className="text-button" onClick={()=>{setForgot(!forgot);setNeedOtp(false);setError('');}}>{forgot?tr("已有账号，返回登录"):tr("忘记密码？")}</button>}
      {error&&!publicSite&&<button type="button" className="text-button" onClick={()=>void refresh()}>{tr("重新连接")}</button>}
    </section>
  </div></main>;
}
