'use client';
import { ReactNode, useEffect, useState } from 'react';
import { api, jsonBody, User } from './api';

export default function AuthGate({ children }: { children: (user: User, logout: () => Promise<void>) => ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [setup, setSetup] = useState(false);
  const [register, setRegister] = useState(false);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [unencrypted,setUnencrypted]=useState(false);
  async function refresh() {
    try { const data = await api<{ user: User | null; setup: boolean }>('/api/auth/me'); setUser(data.user); setSetup(data.setup); setRegister(data.setup); }
    catch (e) { setError(e instanceof Error ? e.message : '本地服务未连接'); }
    finally { setLoading(false); }
  }
  useEffect(() => { setUnencrypted(window.location.protocol==='http:');void refresh(); }, []);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const data = await api<{ user: User }>(`/api/auth/${register ? 'register' : 'login'}`, jsonBody({ username, password, invite_code:inviteCode })); setUser(data.user); setPassword(''); }
    catch (e) { setError(e instanceof Error ? e.message : '登录失败'); }
    finally { setBusy(false); }
  }
  async function logout() { await api('/api/auth/logout', jsonBody({})); setUser(null); setPassword(''); setRegister(false); }
  if (user) return children(user, logout);
  return <main className="auth-screen"><section className="auth-card"><div className="brand-mark"><span>p</span></div><p className="eyebrow">PASTPAPER STUDIO</p><h1>{loading ? '正在连接本地服务…' : setup ? '创建你的学习账号' : register ? '添加一个学习账号' : '欢迎回来'}</h1><p>题库、答案与学习记录保存在这台 Mac。每个账号拥有独立记录。</p>{unencrypted&&<p className="lan-notice">局域网模式：连接未加密。请使用可信 Wi-Fi 和此网站专用密码，不要使用邮箱或其他账户的密码。</p>}{!loading && <form onSubmit={(e) => void submit(e)}><label>用户名<input autoComplete="username" minLength={2} maxLength={40} value={username} onChange={(e) => setUsername(e.target.value)} required /></label><label>密码<input type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={8} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} required /></label>{register&&!setup&&<label>管理员邀请码<input value={inviteCode} onChange={e=>setInviteCode(e.target.value)} autoComplete="off" maxLength={128} required placeholder="向管理员索取，24 小时内有效"/></label>}<small>密码至少 8 位。{setup && '首个账号管理现有题库与本机文件夹。'}</small><button className="button primary-button" disabled={busy}>{busy ? '请稍候…' : register ? '创建账号并进入' : '登录'}</button></form>}{error && <p className="folder-error" role="alert">{error}</p>}{!setup && !loading && <button className="text-button" onClick={() => { setRegister(!register); setError(''); }}>{register ? '已有账号，返回登录' : '创建新学习账号'}</button>}<button className="text-button" onClick={() => void refresh()}>重新连接</button><div className="auth-privacy">ChatGPT 云端 AI 已关闭 · 不会调用付费 API</div></section></main>;
}
