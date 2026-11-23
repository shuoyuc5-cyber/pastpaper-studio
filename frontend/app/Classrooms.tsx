'use client';

import {useEffect, useState, type FormEvent} from 'react';
import {api, jsonBody, type User} from './api';
import Classwork from './Classwork';
import {PreferenceControls,useStudioPreferences,useStudioStatus} from './preferences';

export const classroomText = {
  'Archive class': '归档班级', 'Reopen class': '重新开放班级', 'Archived': '已归档',
  'Classes': '班级', 'My classes': '我的班级', 'Manage classes': '管理班级',
  'Create class': '创建班级', 'Class name': '班级名称', 'Subject': '科目',
  'Grade level': '年级', 'Description': '说明', 'Student capacity': '人数上限',
  'Join a class': '加入班级', 'Class code': '班级码', 'Preview class': '查看班级',
  'Join class': '加入班级', 'Request to join': '申请加入',
  'Join settings': '加入设置', 'Join by code': '允许使用班级码',
  'Admission': '加入方式', 'Manual approval': '老师审批', 'Automatic admission': '自动加入',
  'Code expires in days': '班级码有效天数', 'Save settings': '保存设置',
  'Regenerate code': '重新生成班级码', 'Current code': '当前班级码', 'Code expiration': '班级码到期时间',
  'Never': '无期限', 'Manage': '管理', 'Members': '班级成员', 'Search members': '搜索成员',
  'Active': '已加入', 'Pending approval': '等待审批', 'Approve': '通过', 'Remove': '移除',
  'Remove this student from the class?': '确定移除这名班级成员？',
  'No classes yet.': '还没有班级。', 'No matching members.': '没有匹配的成员。',
  'Class created.': '班级已创建。', 'Join request sent.': '加入申请已发送。',
  'You joined the class.': '已加入班级。', 'Join settings saved.': '加入设置已保存。',
  'Member approved.': '已通过成员申请。', 'Member removed.': '已移除成员。',
  'Loading classes…': '正在加载班级…', 'Could not complete the action.': '操作未完成。',
  'Classroom language': '班级页面语言', 'Classroom appearance': '班级页面外观',
  'Light': '浅色', 'Dark': '深色', 'System': '跟随系统', 'Open class': '进入班级',
  'Class membership, answers and grades are saved on the host for classroom use.': '班级成员、答卷和成绩保存在主机上，供本班教学使用。',
} as const;

type Admission = 'approval' | 'automatic';
export type Classroom = {id:string; name:string; subject:string; grade:string; description:string};
type Managed = Classroom & {archived?:number; capacity:number|null; admission:Admission; join_code:string; join_enabled:number; join_expires_at:number|null};
type Joined = Classroom & {status:'pending'|'active'};
type Preview = Classroom & {admission:Admission};
type Member = {id:string; username:string; status:Joined['status']};
type ClassList = {managed:Managed[]; joined:Joined[]};

export default function Classrooms({user}: {user:User}) {
  const {lang,theme}=useStudioPreferences();
  const statusCopy=useStudioStatus();
  const [data,setData] = useState<ClassList>({managed:[],joined:[]});
  const [busy,setBusy] = useState(false), [loading,setLoading] = useState(true);
  const [error,setError] = useState(''), [notice,setNotice] = useState('');
  const [openId,setOpenId] = useState(''), [members,setMembers] = useState<Member[]>([]);
  const [code,setCode] = useState(''), [preview,setPreview] = useState<Preview|null>(null), [memberSearch,setMemberSearch] = useState('');
  const [expiry,setExpiry] = useState(''), [inviteEnabled,setInviteEnabled] = useState(true), [admission,setAdmission] = useState<Admission>('approval');
  const [activeClass,setActiveClass] = useState<Classroom|null>(null);
  const [initialAssignment,setInitialAssignment] = useState('');
  const canTeach = user.role==='teacher'||user.role==='admin';
  const managed = canTeach?data.managed.find(room=>room.id===openId):undefined;
  const t = (key:keyof typeof classroomText) => lang==='en' ? key : classroomText[key];

  useEffect(()=>{
    const assignment=new URLSearchParams(location.search).get('assignment')||'';
    if(/^[a-f0-9-]{36}$/.test(assignment))setInitialAssignment(assignment);
  },[]);
  function classApi<T>(path:string,init?:RequestInit){
    return api<T>('/api/classroom'+path,{...init,headers:{...init?.headers,'X-Studio-Language':lang}});
  }
  async function refresh(){setData(await classApi<ClassList>('/classes'));}
  useEffect(()=>{
    let mounted=true;
    api<ClassList>('/api/classroom/classes').then(list=>{if(mounted)setData(list);})
      .catch(()=>{if(mounted)setError('load');}).finally(()=>{if(mounted)setLoading(false);});
    return()=>{mounted=false;};
  },[user.role]);
  async function act(run:()=>Promise<void>, outcome?:keyof typeof classroomText){
    setBusy(true);setError('');setNotice('');
    try{await run();if(outcome)setNotice(outcome);}
    catch(e){setError(e instanceof Error?e.message:t('Could not complete the action.'));}
    finally{setBusy(false);}
  }

  function create(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const form=event.currentTarget;
    const fields=new FormData(form);
    const text=(name:string)=>String(fields.get(name)||'').trim();
    void act(async()=>{
      await classApi('/classes',jsonBody({
        name:text('name'),subject:text('subject'),grade:text('grade'),description:text('description'),
        capacity:Number(text('capacity'))||null,expires_in_days:Number(text('expiry'))||null,admission:text('admission'),
      }));
      form.reset();await refresh();
    },'Class created.');
  }
  function lookup(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    setPreview(null);
    void act(async()=>setPreview(await classApi<Preview>('/lookup',jsonBody({code}))));
  }
  function join(){
    void act(async()=>{
      const room=await classApi<Joined>('/join',jsonBody({code}));
      setPreview(null);setCode('');await refresh();
      setNotice(room.status==='pending'?'Join request sent.':'You joined the class.');
    });
  }
  async function loadMembers(roomId:string){
    setMembers((await classApi<{members:Member[]}>(`/classes/${roomId}/members`)).members);
  }
  function openManagement(room:Managed){
    void act(async()=>{
      await loadMembers(room.id);
      setOpenId(room.id);setInviteEnabled(!!room.join_enabled);setAdmission(room.admission);setExpiry('');setMemberSearch('');setActiveClass(room);
    });
  }
  function saveSettings(regenerate:boolean){
    if(!managed)return;
    void act(async()=>{
      await classApi(`/classes/${managed.id}/invitation`,jsonBody({
        enabled:inviteEnabled,admission,regenerate,...(expiry===''?{}:{expires_in_days:Number(expiry)||null}),
      },'PUT'));
      setExpiry('');await refresh();
    },'Join settings saved.');
  }
  function changeMember(member:Member,remove:boolean){
    if(!managed||remove&&!confirm(t('Remove this student from the class?')))return;
    void act(async()=>{
      await classApi(`/classes/${managed.id}/members/${member.id}`,{method:remove?'DELETE':'PUT'});
      await loadMembers(managed.id);
    },remove?'Member removed.':'Member approved.');
  }

  return <div className="studio-workspace classroom" data-theme={theme} lang={lang}>
    <div className="workspace-heading">
      <h1>{canTeach?(lang==='en'?'Teaching dashboard':'教学工作台'):(lang==='en'?'Student dashboard':'学生工作台')}</h1>
      <PreferenceControls appearanceOnly/>
    </div>
    <p>{t('Class membership, answers and grades are saved on the host for classroom use.')}</p>
    {loading&&<p role="status">{t('Loading classes…')}</p>}
    {error&&<p className="classroom-error" role="alert">{error==='load'?t('Could not complete the action.'):statusCopy(error)}</p>}
    {notice&&<p role="status">{t(notice as keyof typeof classroomText)}</p>}
    {canTeach&&<section className="work-panel">
      <h2>{t('Manage classes')}</h2>
      <form className="classroom-form" onSubmit={create}>
        <h3>{t('Create class')}</h3>
        <div className="classroom-fields">
          <label>{t('Class name')}<input name="name" required maxLength={100}/></label>
          <label>{t('Subject')}<input name="subject" required maxLength={100}/></label>
          <label>{t('Grade level')}<input name="grade" maxLength={80}/></label>
          <label>{t('Student capacity')}<input name="capacity" type="number" min={1} max={1000}/></label>
          <label>{t('Admission')}<select name="admission" defaultValue="approval"><option value="approval">{t('Manual approval')}</option><option value="automatic">{t('Automatic admission')}</option></select></label>
          <label>{t('Code expires in days')}<input name="expiry" type="number" min={1} max={365}/></label>
        </div>
        <label>{t('Description')}<textarea name="description" maxLength={1600}/></label>
        <div><button disabled={busy}>{t('Create class')}</button></div>
      </form>
      {data.managed.map(room=><div key={room.id} className="classroom-row"><strong>{room.name}</strong><span>{room.subject}{room.archived?' · '+t('Archived'):''}</span><button disabled={busy} onClick={()=>openManagement(room)}>{t('Manage')}</button></div>)}
    </section>}
    <section className="work-panel">
      <h2>{t('My classes')}</h2>
      {!data.joined.length&&!loading&&<p>{t('No classes yet.')}</p>}
      {data.joined.map(room=><div key={room.id} className="classroom-row">
        <strong>{room.name}</strong><span>{room.subject} · {t(room.status==='active'?'Active':'Pending approval')}</span>
        {room.status==='active'&&<button onClick={()=>{setActiveClass(room);setOpenId('');}}>{t('Open class')}</button>}
      </div>)}
      <form onSubmit={lookup}>
        <h3>{t('Join a class')}</h3>
        <div className="work-actions"><label>{t('Class code')}<input autoComplete="off" value={code} required maxLength={32} onChange={e=>{setCode(e.target.value.toUpperCase());setPreview(null);}}/></label><button disabled={busy}>{t('Preview class')}</button></div>
      </form>
      {preview&&<div className="classroom-row"><strong>{preview.name}</strong><span>{preview.subject}{preview.grade&&` · ${preview.grade}`}</span>{preview.description&&<p>{preview.description}</p>}<button disabled={busy} onClick={join}>{t(preview.admission==='approval'?'Request to join':'Join class')}</button></div>}
    </section>
    {managed&&<section className="work-panel">
      <h2>{managed.name}</h2>
      {user.publicMode&&<button type="button" disabled={busy} onClick={()=>void act(async()=>{
        await classApi(`/classes/${managed.id}/archive?archived=${!managed.archived}`,jsonBody({},'PUT'));
        await refresh();
      })}>{t(managed.archived?'Reopen class':'Archive class')}</button>}
      <h3>{t('Join settings')}</h3>
      <p>{t('Current code')} <code>{managed.join_code}</code></p>
      <p>{t('Code expiration')} {managed.join_expires_at?new Date(managed.join_expires_at*1000).toLocaleString(lang):t('Never')}</p>
      <form onSubmit={event=>{event.preventDefault();saveSettings(false);}}>
        <div className="work-actions">
          <label><input type="checkbox" checked={inviteEnabled} onChange={e=>setInviteEnabled(e.target.checked)}/>{t('Join by code')}</label>
          <label>{t('Admission')}<select value={admission} onChange={e=>setAdmission(e.target.value as Admission)}><option value="approval">{t('Manual approval')}</option><option value="automatic">{t('Automatic admission')}</option></select></label>
          <label>{t('Code expires in days')}<input type="number" min={0} max={365} value={expiry} onChange={e=>setExpiry(e.target.value)}/></label>
          <button disabled={busy}>{t('Save settings')}</button>
          <button type="button" disabled={busy} onClick={()=>saveSettings(true)}>{t('Regenerate code')}</button>
        </div>
      </form>
      <h3>{t('Members')}</h3>
      <label>{t('Search members')}<input type="search" value={memberSearch} onChange={e=>setMemberSearch(e.target.value)}/></label>
      {members.filter(member=>member.username.toLowerCase().includes(memberSearch.trim().toLowerCase())).map(member=><div key={member.id} className="classroom-row">
        <strong>{member.username}</strong><span>{t(member.status==='active'?'Active':'Pending approval')}</span>
        {member.status==='pending'&&<button disabled={busy} onClick={()=>changeMember(member,false)}>{t('Approve')}</button>}
        <button disabled={busy} onClick={()=>changeMember(member,true)}>{t('Remove')}</button>
      </div>)}
      {!members.some(member=>member.username.toLowerCase().includes(memberSearch.trim().toLowerCase()))&&<p>{t('No matching members.')}</p>}
    </section>}
    {activeClass&&!managed&&<section className="work-panel"><h2>{activeClass.name}</h2><p>{activeClass.subject}</p>{activeClass.description&&<p>{activeClass.description}</p>}</section>}
    <Classwork key={activeClass?.id||'lookup'} classId={activeClass?.id} manage={!!managed} lang={lang} initialAssignment={!activeClass?initialAssignment:undefined}/>
  </div>;
}
