'use client';

import {useEffect,useRef,useState,type FormEvent,type ReactNode} from 'react';
import {api,jsonBody} from './api';
import {validEmail} from './email';
import {PreferenceControls,roleLabel,useStudioPreferences} from './preferences';

type Role = 'teacher'|'student';
type Account = {id:string;username:string;email:string|null;role:string;enabled:boolean;created_at:string;owned_classes:number;local_allowed:boolean;cloud_allowed:boolean};
type Audit = {actor:string;target:string;previous_role:string;new_role:string;created_at:string};
type Room = {id:string;name:string;subject:string};
type Ownership = {classes:Room[];eligible_successors:string[]};
type Host = {version:string;database:boolean;lan_enabled:boolean};

function AccountDialog({title,close,children,busy}:{title:string;close:()=>void;children:ReactNode;busy:boolean}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    const dialog=ref.current;
    dialog?.showModal();
    return ()=>dialog?.close();
  },[]);
  return <dialog ref={ref} aria-labelledby="account-dialog-title" className="question-dialog account-dialog"
    onCancel={event=>{event.preventDefault();if(!busy)close();}}>
    <h2 id="account-dialog-title">{title}</h2>{children}
  </dialog>;
}

export default function AccountPermissions({publicMode=false}:{publicMode?:boolean}){
  const {lang}=useStudioPreferences();
  const en=lang==='en', t=(english:string,chinese:string)=>en?english:chinese;
  const [accounts,setAccounts]=useState<Account[]>([]),[query,setQuery]=useState('');
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[guestWrites,setGuestWrites]=useState(false);
  const [notice,setNotice]=useState<[string,string]|null>(null),[error,setError]=useState('');
  const [audit,setAudit]=useState<Audit[]|null>(null),[host,setHost]=useState<Host|null>(null),[invite,setInvite]=useState('');
  const [dialog,setDialog]=useState<'create'|'role'|'account'|null>(null);
  const [target,setTarget]=useState<Account|null>(null),[role,setRole]=useState<Role>('student');
  const [ownership,setOwnership]=useState<Ownership|null>(null),[replacement,setReplacement]=useState('');
  const [confirmedDelete,setConfirmedDelete]=useState(false);
  const [accountEnabled,setAccountEnabled]=useState(true);

  async function call<T>(path:string,init?:RequestInit){
    return api<T>('/api/admin/'+path,{...init,headers:{...init?.headers,'X-Studio-Language':lang}});
  }
  async function refresh(){
    const data=await call<{accounts:Account[];guest_writes:boolean}>('accounts');
    setAccounts(data.accounts);setGuestWrites(data.guest_writes);
  }
  useEffect(()=>{
    void api<{accounts:Account[];guest_writes:boolean}>('/api/admin/accounts')
      .then(data=>{setAccounts(data.accounts);setGuestWrites(data.guest_writes);})
      .catch(e=>setError(e.message)).finally(()=>setLoading(false));
  },[]);
  const visible=accounts.filter(a=>[a.username,a.email||''].some(value=>value.toLowerCase().includes(query.trim().toLowerCase())));
  const recipients=accounts.filter(a=>ownership?.eligible_successors.includes(a.id));
  const needsOwner=role==='student'&&!!ownership?.classes.length;
  const canTransfer=recipients.some(a=>a.id===replacement);
  const formatDate=(value:string,showTime=false)=>{
    const date=new Date(value);
    return Number.isNaN(date.getTime())?'—':new Intl.DateTimeFormat(lang,{
      dateStyle:'medium',...(showTime?{timeStyle:'short'}:{}),
    }).format(date);
  };
  const englishErrors:Record<string,string>={
    '此操作需要管理员权限':'Administrator access is required.',
    '请登录本地学习账号':'Sign in to your host account.',
    '此用户名已被使用':'This display name is already in use.',
    '此电子邮箱已绑定其他账号':'This email address is already linked to another account.',
    '账号不存在':'Account not found.',
    '请输入有效的电子邮箱地址。':'Enter a valid email address.',
    '请先通过角色管理转交此账号的班级。':'Transfer this account’s classes in Manage role first.',
    '请求格式不正确，请核对字段和长度。':'Check the required fields and try again.',
  };
  const showError=(value:string)=>en&&/\p{Script=Han}/u.test(value)?englishErrors[value]||'The request could not be completed. Refresh the page and try again.':value;
  async function act(run:()=>Promise<void>){
    setError('');setNotice(null);setBusy(true);
    try{await run();}catch(e){setError(e instanceof Error?e.message:'The request could not be completed.');}
    finally{setBusy(false);}
  }
  function close(){setDialog(null);setError('');setTarget(null);}
  async function loadAudit(){setAudit((await call<{events:Audit[]}>('role-audit')).events);}
  function openRole(a:Account){
    setTarget(a);setRole(a.role==='teacher'?'teacher':'student');setReplacement('');setOwnership(null);setDialog('role');
    void act(async()=>setOwnership(await call<Ownership>(`accounts/${a.id}/owned-classes`)));
  }
  function submitRole(event:FormEvent){
    event.preventDefault();
    if(!target||!ownership||(needsOwner&&!canTransfer))return;
    void act(async()=>{
      await call(`accounts/${target.id}/role`,jsonBody({role,replacement_id:needsOwner?replacement:null},'PUT'));
      setDialog(null);setTarget(null);
      setNotice([`${target.username} now has the ${roleLabel(role,true)} role.`,`${target.username} 的角色已更新为${roleLabel(role,false)}。`]);
      await refresh();if(audit)await loadAudit();
    });
  }
  function create(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const values=new FormData(event.currentTarget),email=String(values.get('email')||'').trim();
    if(!validEmail(email)){setError('请输入有效的电子邮箱地址。');return;}
    void act(async()=>{
      await call('accounts',jsonBody({email,username:String(values.get('name')||'').trim(),password:values.get('password')}));
      setDialog(null);setNotice(['Student account created.','学生账号已创建。']);await refresh();
    });
  }
  function updateEmail(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!target)return;
    const email=String(new FormData(event.currentTarget).get('email')||'').trim();
    if(!validEmail(email)){setError('请输入有效的电子邮箱地址。');return;}
    void act(async()=>{await call(`accounts/${target.id}/email`,jsonBody({email},'PUT'));await refresh();
      setNotice(['Sign-in email saved.','登录邮箱已保存。']);});
  }
  function updateStatus(){
    if(!target)return;
    void act(async()=>{
      await call(`accounts/${target.id}/ai-permissions`,jsonBody({
        enabled:accountEnabled,local_allowed:target.local_allowed,cloud_allowed:target.cloud_allowed,
      },'PUT'));
      setDialog(null);setTarget(null);await refresh();
      setNotice(['Account status saved.','账号状态已保存。']);
    });
  }
  function sendAccountLink(){
    if(!target)return;
    void act(async()=>{
      await call(`accounts/${target.id}/setup-link`,jsonBody({}));
      setDialog(null);setTarget(null);
      setNotice(['Account email queued.','账号邮件已排队。']);
    });
  }
  function deleteAccount(){
    if(!target)return;
    void act(async()=>{
      await call(`accounts/${target.id}`,{method:'DELETE'});setDialog(null);setTarget(null);await refresh();
      setNotice(['Account deleted.','账号已删除。']);
    });
  }

  const roleInfo={
    admin:t('Manages accounts, system roles and host settings.','管理账号、系统角色和主机设置。'),
    teacher:t('Manages authorized classes, publishes assignments and reviews results.','管理有权限的班级、发布作业并查看成绩。'),
    student:t('Joins classes, completes assignments and views personal results.','加入班级、完成作业并查看自己的成绩。'),
  };
  const cancel=<button type="button" disabled={busy} onClick={close}>{t('Cancel','取消')}</button>;
  const dialogError=error&&<p className="account-error" role="alert">{showError(error)}</p>;
  const status=notice&&<p role="status">{t(...notice)}</p>;

  return <div className="studio-workspace classroom user-management">
    <div className="workspace-heading"><div>
      <h1>{t('User Management','用户管理')}</h1>
      <p>{t('Administration','管理')} / {t('User Management','用户管理')}</p>
    </div><PreferenceControls appearanceOnly/></div>
    <section className="work-panel">
      <div className="management-toolbar">
        <label>{t('Search users','搜索用户')}<input type="search" value={query} onChange={event=>setQuery(event.target.value)}
          placeholder={t('Display name or email','显示名称或邮箱')}/></label>
        <button className="studio-primary" disabled={busy||loading} onClick={()=>{setError('');setNotice(null);setDialog('create');}}>{t('Create student account','创建学生账号')}</button>
      </div>
      {!dialog&&dialogError}
      {!dialog&&status}
      <p>{t('System roles and class membership are managed separately.','系统角色与班级成员资格分别管理。')}</p>
      {loading?<p role="status">{t('Loading users…','正在加载用户…')}</p>:<table className="account-table">
        <thead><tr>{[
          t('Display name','显示名称'),t('Email address','电子邮箱'),t('Current role','当前角色'),
          t('Account status','账号状态'),t('Date created','创建日期'),t('Actions','操作'),
        ].map(label=><th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{visible.map(a=><tr key={a.id}>
          <th scope="row">{a.username}</th>
          <td data-label={t('Email address','电子邮箱')}>{a.email||t('No email linked','尚未绑定')}</td>
          <td data-label={t('Current role','当前角色')}><span className="role-pill">{roleLabel(a.role,en)}</span></td>
          <td data-label={t('Account status','账号状态')}>{a.enabled?t('Active','启用'):t('Disabled','停用')}</td>
          <td data-label={t('Date created','创建日期')}><time dateTime={a.created_at}>{formatDate(a.created_at)}</time></td>
          <td><div className="account-actions">
            <button type="button" disabled={busy||a.role==='admin'} onClick={()=>openRole(a)}>{t('Manage role','管理角色')}</button>
            <button type="button" disabled={busy} onClick={()=>{setError('');setNotice(null);setTarget(a);setAccountEnabled(!!a.enabled);setConfirmedDelete(false);setDialog('account');}}>{t('Account settings','账号设置')}</button>
          </div></td>
        </tr>)}</tbody>
      </table>}
      {!loading&&!visible.length&&<p>{t('No matching accounts.','没有匹配的账号。')}</p>}
    </section>
    <section className="work-panel">
      <div className="work-actions">
        <button disabled={busy} onClick={()=>void act(loadAudit)}>{t('Role change history','角色变更记录')}</button>
        <button disabled={busy} onClick={()=>void act(async()=>setHost(await call<Host>('host-status')))}>{t('Host status','主机状态')}</button>
        {guestWrites&&<button disabled={busy} onClick={()=>void act(async()=>setInvite((await call<{code:string}>('invitations',jsonBody({}))).code))}>{t('Generate one-time invitation','生成一次性邀请码')}</button>}
      </div>
      {invite&&<p>{t('One-time invitation, valid for 24 hours','一次性邀请码，24 小时有效')} <code>{invite}</code></p>}
      {host&&<p role="status">{host.database?t('Database connected','数据库已连接'):t('Database unavailable','数据库未连接')} · {host.version} · {host.lan_enabled?t('LAN enabled','局域网已启用'):t('Local only','仅本机')}</p>}
      {audit&&<ul className="account-audit">{audit.map((event,index)=><li key={index}>{formatDate(event.created_at,true)} · {event.actor} · {event.target} · {roleLabel(event.previous_role,en)} → {roleLabel(event.new_role,en)}</li>)}
      {!audit.length&&<li>{t('No role changes yet.','暂无角色变更。')}</li>}</ul>}
    </section>

    {dialog==='role'&&target&&<AccountDialog busy={busy} close={close} title={t('Manage role','管理角色')}>
      <form className="classroom-form" onSubmit={submitRole}>
        <p><strong>{target.username}</strong> · {target.email||t('No email linked','尚未绑定邮箱')}</p>
        <p>{t('Current role','当前角色')} · {roleLabel(target.role,en)}</p>
        <label>{t('New role','新角色')}<select value={role} onChange={event=>{setRole(event.target.value as Role);setError('');}}>
          <option value="teacher">{roleLabel('teacher',en)}</option><option value="student">{roleLabel('student',en)}</option>
        </select></label>
        <dl className="role-explanations">{Object.entries(roleInfo).map(([value,description])=><div key={value}>
          <dt>{roleLabel(value,en)}</dt><dd>{description}</dd>
        </div>)}</dl>
        {needsOwner&&<>
          <p>{t('Transfer these classes before assigning Student. Assignments, members and grades stay with the class.','设为学生前请转交以下班级。作业、成员和成绩仍保留在原班级。')}</p>
          <ul className="account-audit">{ownership?.classes.map(room=><li key={room.id}>{room.name} · {room.subject}</li>)}</ul>
          {recipients.length?<label>{t('New class owner','新班级负责人')}<select required value={replacement} onChange={event=>setReplacement(event.target.value)}>
            <option value="">{t('Select an active teacher or administrator','选择启用中的老师或管理员')}</option>
            {recipients.map(a=><option value={a.id} key={a.id}>{a.username} · {roleLabel(a.role,en)}</option>)}
          </select></label>:<p>{t('No active teacher or administrator can take over these classes. The new owner must have no membership or student work in any listed class.','没有可接管这些班级的启用中老师或管理员。新负责人在所列班级中须没有成员身份或学生答题记录。')}</p>}
        </>}
        {dialogError}
        {!ownership&&busy&&<p role="status">{t('Checking class ownership…','正在检查班级归属…')}</p>}
        <div className="work-actions">{cancel}<button className="studio-primary" disabled={busy||!ownership||(target.role===role&&!needsOwner)||(needsOwner&&!canTransfer)}>{t('Confirm role change','确认更改角色')}</button></div>
      </form>
    </AccountDialog>}

    {dialog==='create'&&<AccountDialog busy={busy} close={close} title={t('Create student account','创建学生账号')}>
      <form className="classroom-form" onSubmit={create}>
        <label>{t('Display name','显示名称')}<input name="name" minLength={2} maxLength={40} required autoComplete="off"/></label>
        <label>{t('Email address','电子邮箱')}<input name="email" type="email" maxLength={254} required autoComplete="off"/></label>
        <label>{t('Initial password','初始密码')}<input name="password" type="password" minLength={publicMode?12:8} maxLength={128} required autoComplete="new-password"/></label>
        {dialogError}<div className="work-actions">{cancel}<button className="studio-primary" disabled={busy}>{t('Create account','创建账号')}</button></div>
      </form>
    </AccountDialog>}

    {dialog==='account'&&target&&<AccountDialog busy={busy} close={close} title={t('Account settings','账号设置')}>
      <p><strong>{target.username}</strong> · {roleLabel(target.role,en)}</p>
      <form className="classroom-form" onSubmit={updateEmail}>
        <label>{t('Sign-in email','登录邮箱')}<input type="email" name="email" required maxLength={254} defaultValue={target.email||''}/></label>
        <div><button type="submit" disabled={busy}>{t('Save email','保存邮箱')}</button></div>
      </form>
      {target.role!=='admin'&&<>
        <div className="work-actions"><label><input type="checkbox" checked={accountEnabled} onChange={event=>setAccountEnabled(event.target.checked)}/>{t('Account active','启用账号')}</label>
          <button disabled={busy||accountEnabled===!!target.enabled} onClick={updateStatus}>{t('Save status','保存状态')}</button></div>
        {confirmedDelete?<p>{t('Delete this sign-in account? Existing learning records are retained.','删除此登录账号？现有学习记录会保留。')}</p>:null}
      </>}
      {dialogError}{status}
      {publicMode&&target.role!=='admin'&&target.email&&<button type="button" disabled={busy} onClick={sendAccountLink}>{t('Send setup or reset email','发送设置或重置密码邮件')}</button>}
      <div className="work-actions">{cancel}{target.role!=='admin'&&<button disabled={busy} onClick={()=>confirmedDelete?deleteAccount():setConfirmedDelete(true)}>
        {confirmedDelete?t('Confirm deletion','确认删除'):t('Delete account','删除账号')}</button>}</div>
    </AccountDialog>}
  </div>;
}
