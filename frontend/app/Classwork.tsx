'use client';

import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react';
import {api, jsonBody} from './api';
import {localizedStatus} from './preferences';

type Language = 'en'|'zh-CN';
type Kind = 'short'|'single'|'multiple'|'boolean'|'fill'|'number';
type Question = {text:string;kind:Kind;marks:number;options:string[];accepted:string[];topic:string;case_sensitive:boolean;ignore_punctuation:boolean;tolerance:number;partial_credit:boolean};
type Rules = {opens_at:number|null;deadline:number|null;minutes:number|null;attempts:number;allow_late:boolean;shuffle_questions:boolean;shuffle_options:boolean;show_results:boolean;reveal_answers:boolean;leaderboard:boolean};
type Assignment = {id:string;title:string;version:number;class_id:string;published_at:number|null;code?:string;rules:Rules};
type StudentQuestion = Pick<Question,'text'|'kind'|'marks'|'topic'> & {position:number;options:{id:string;text:string}[];accepted?:string[]};
type Answers = Record<number,string|string[]>;
type Grade = {marks:number|null;feedback:string};
type Metrics = {marks:number;available_marks:number;total_marks:number;graded:number;pending:number;accuracy:number|null;percentage:number|null};
type Attempt = {id:string;number:number;questions:StudentQuestion[];answers:Answers;revision:number;submitted_at:number|null;expires_at:number|null;grades?:Record<number,Grade>;metrics?:Metrics};
type Submission = {id:string;username:string|null;number:number;answers:Answers;grades:Record<number,Grade>;metrics:Metrics};
type Ranking = Metrics & {rank:number;nickname:string;mine:boolean};
type ClassAnalytics = {students:number;published:number;assignments:{id:string;title:string;completed:number;completion:number|null;average_score:number|null;average_accuracy:number|null;questions:{position:number;graded:number;accuracy:number|null}[]}[];topics:{topic:string;correct:number;graded:number}[]};

const words = {
  'Assignments':'作业','Find assignment by code':'通过作业码打开','Assignment code':'作业码','Open assignment':'打开作业',
  'Create assignment':'创建作业','Assignment title':'作业标题','Question bank':'题库','Question count':'题数',
  'Total marks':'总分','Subject code':'科目代码','Topic':'知识点','Difficulty':'难度','Any':'不限',
  'Easy':'简单','Medium':'中等','Hard':'较难','Generate from bank':'从题库组卷','Questions':'题目',
  'Question text':'题目正文','Question type':'题型','Marks':'分值','Options, one per line':'选项，每行一个',
  'Correct options':'正确选项','Accepted answers, one per line':'可接受答案，每行一个',
  'Add question':'添加题目','Remove question':'移除题目','Single choice':'单选','Multiple choice':'多选',
  'True / false':'判断题','Fill in the blank':'填空','Numerical':'数值题','Short answer':'简答题',
  'True':'正确','False':'错误','Case sensitive':'区分大小写','Ignore punctuation':'忽略标点',
  'Numerical tolerance':'数值容差','Partial credit':'允许部分得分','Publish at':'计划发布时间',
  'Deadline':'截止时间','Time limit in minutes':'限时（分钟）','Maximum attempts':'最多作答次数',
  'Accept late work':'接受逾期提交','Shuffle questions':'随机排列题目','Shuffle options':'随机排列选项',
  'Show results':'显示结果','Reveal answers':'公布正确答案','Enable leaderboard':'开启排行榜',
  'Save assignment draft':'保存作业草稿','Edit draft':'编辑草稿','Create new version':'创建新版本',
  'Publish':'发布','Draft':'草稿','Published':'已发布','Scheduled':'待发布','Version':'版本','Shareable link':'分享链接',
  'No assignments yet.':'暂无作业。','Assignment draft saved.':'作业草稿已保存。','Assignment published.':'作业已发布。',
  'Publish this version?':'确认发布这个版本？','Confirm publication':'确认发布','Cancel':'取消','Loading…':'正在加载…','Action could not be completed.':'操作未完成。',
  'Start attempt':'开始作答','Previous attempts':'以往答卷','Attempt':'答卷','Previous':'上一题','Next':'下一题',
  'Your answer':'你的答案','Save answers':'保存答卷','Draft saved.':'答卷草稿已保存。','Saving…':'保存中…',
  'Submit answers':'提交答卷','Submitted.':'答卷已提交。','Answered':'已答','Unanswered':'未答','Submit now?':'现在提交吗？',
  'Continue editing':'继续作答','Confirm submission':'确认提交','Reload saved answers':'重新读取已保存答卷',
  'Remaining time':'剩余时间','Time expired':'作答时间已结束','Results':'结果','Accuracy':'正确率',
  'Score percentage':'得分率','Pending review':'等待批改','Accepted answers':'正确答案','Feedback':'评语',
  'Review submissions':'批改答卷','No submissions yet.':'还没有答卷。','Deleted account':'已删除的账号',
  'Save grade':'保存评分','Grade saved.':'评分已保存。','Leaderboard':'排行榜','Rank':'名次',
  'Nickname':'昵称','No eligible results yet.':'暂无符合排名条件的成绩。','You':'你','Assignment authoring':'作业编写',
  'Create a draft before publishing.':'先保存草稿，再发布作业。','Completion':'完成情况','Completed attempts':'已提交答卷',
  'Import an exam document':'导入试卷文件','Import file':'导入文件','Import and preview':'提取并预览',
  'Review extracted text, options and marks. Diagrams and original formatting may need manual reference.':'请核对提取的文字、选项和分值。图形和原始排版可能需要对照原卷。',
  'Split at cursor':'在光标处分题','Merge with next':'与下一题合并',
  'Place the cursor between two nonempty sections.':'请把光标放在两段非空题目文字之间。',
  'Merged question exceeds the text or marks limit.':'合并后超过单题文字或分值上限。',
  'Class performance':'班级成绩','Period':'时间范围','Last 7 days':'最近 7 天','Last 30 days':'最近 30 天','All time':'全部时间',
  'Load class performance':'查看班级成绩','Active students':'在班学生','Published assignments':'已发布作业',
  'Average score percentage':'平均得分率','Average accuracy':'平均正确率','Question accuracy':'每题正确率','By topic':'按知识点',
} as const;
type Label = keyof typeof words;
const typeNames:Record<Kind,Label>={short:'Short answer',single:'Single choice',multiple:'Multiple choice',boolean:'True / false',fill:'Fill in the blank',number:'Numerical'};
const emptyQuestion = ():Question=>({text:'',kind:'short',marks:1,options:[],accepted:[],topic:'',case_sensitive:false,ignore_punctuation:false,tolerance:0,partial_credit:false});
const defaultRules:Rules={opens_at:null,deadline:null,minutes:null,attempts:1,allow_late:false,shuffle_questions:false,shuffle_options:false,show_results:true,reveal_answers:false,leaderboard:false};
const toggles: [keyof Rules,Label][]=[
  ['allow_late','Accept late work'],['shuffle_questions','Shuffle questions'],['shuffle_options','Shuffle options'],
  ['show_results','Show results'],['reveal_answers','Reveal answers'],['leaderboard','Enable leaderboard'],
];
const displayAnswer=(answer?:string|string[])=>Array.isArray(answer)?answer.join(', '):answer||'';
const answered=(answer?:string|string[])=>Array.isArray(answer)?answer.length>0:!!answer?.trim();

function localDate(timestamp:number|null){
  if(!timestamp)return '';
  const date=new Date(timestamp*1000);
  return new Date(date.getTime()-date.getTimezoneOffset()*60_000).toISOString().slice(0,16);
}

export default function Classwork({classId,manage,lang,initialAssignment}:{classId?:string;manage:boolean;lang:Language;initialAssignment?:string}) {
  const t=(key:Label)=>lang==='en'?key:words[key];
  const call=useCallback(<T,>(path:string,init?:RequestInit)=>api<T>('/api/classroom'+path,{...init,headers:{...init?.headers,'X-Studio-Language':lang}}),[lang]);
  const [assignments,setAssignments]=useState<Assignment[]>([]);
  const [target,setTarget]=useState<Assignment|null>(null);
  const [code,setCode]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState<Label|null>(null);
  const [editing,setEditing]=useState(false),[editId,setEditId]=useState(''),[previousId,setPreviousId]=useState('');
  const [pendingPublish,setPendingPublish]=useState('');
  const [title,setTitle]=useState(''),[questions,setQuestions]=useState<Question[]>([emptyQuestion()]),[rules,setRules]=useState<Rules>(defaultRules);
  const [grading,setGrading]=useState<{assignment:Assignment;questions:Question[];rows:Submission[]}|null>(null);
  const [attempts,setAttempts]=useState<Attempt[]>([]),[attempt,setAttempt]=useState<Attempt|null>(null),[draft,setDraft]=useState<Answers>({});
  const [position,setPosition]=useState(0),[confirming,setConfirming]=useState(false),[paused,setPaused]=useState(false);
  const [saving,setSaving]=useState(false),[clock,setClock]=useState(0),[ranking,setRanking]=useState<Ranking[]|null>(null);
  const [analytics,setAnalytics]=useState<ClassAnalytics|null>(null),[period,setPeriod]=useState('all');
  const openedLink=useRef('');
  const dirty=!!attempt&&JSON.stringify(attempt.answers)!==JSON.stringify(draft);
  const remaining=attempt?.expires_at?Math.max(0,attempt.expires_at-clock):null;
  const expired=remaining===0&&clock>0;
  const loadList=useCallback(async()=>{
    if(!classId){setAssignments([]);return;}
    const data=await call<{assignments:Assignment[]}>(`/classes/${classId}/assignments?manage=${manage}`);
    setAssignments(data.assignments);
  },[call,classId,manage]);
  const loadStudent=useCallback(async(id:string)=>{
    const current=await call<Assignment & {attempts:Attempt[]}>(`/assignments/${id}`);
    setTarget(current);setAttempts(current.attempts);setAttempt(null);setDraft({});setRanking(null);setPaused(false);
  },[call]);
  useEffect(()=>{loadList().catch(e=>setError(e.message));},[loadList]);
  useEffect(()=>{
    if(initialAssignment&&openedLink.current!==initialAssignment){
      openedLink.current=initialAssignment;
      loadStudent(initialAssignment).catch(e=>setError(e.message));
    }
  },[initialAssignment,loadStudent]);
  useEffect(()=>{
    if(!attempt?.expires_at||attempt.submitted_at)return;
    const tick=()=>setClock(Math.floor(Date.now()/1000));tick();
    const timer=setInterval(tick,1000);
    return()=>clearInterval(timer);
  },[attempt?.expires_at,attempt?.submitted_at]);

  async function act(run:()=>Promise<void>,success?:Label){
    setBusy(true);setError('');setNotice(null);
    try{await run();if(success)setNotice(success);}
    catch(e){setError(e instanceof Error?e.message:t('Action could not be completed.'));}
    finally{setBusy(false);}
  }
  function selectAttempt(value:Attempt){
    setAttempt(value);setDraft(value.answers);setPosition(0);setConfirming(false);setPaused(false);
  }
  const write=useCallback(async(submit:boolean)=>{
    if(!target||!attempt||attempt.submitted_at)return;
    setSaving(true);setError('');
    try{
      const updated=await call<Attempt>(`/assignments/${target.id}/attempts/${attempt.id}${submit?'/submit':''}`,jsonBody({revision:attempt.revision,answers:draft},submit?'POST':'PUT'));
      setAttempt(updated);setAttempts(rows=>[updated,...rows.filter(row=>row.id!==updated.id)]);
      setNotice(submit?'Submitted.':'Draft saved.');setPaused(false);setConfirming(false);
    }catch(e){
      setError(e instanceof Error?e.message:'Action could not be completed.');
      setPaused(true);
    }finally{setSaving(false);}
  },[attempt,call,draft,target]);
  useEffect(()=>{
    if(!dirty||paused||saving||busy||confirming||expired||attempt?.submitted_at)return;
    const timer=setTimeout(()=>{void write(false);},800);
    return()=>clearTimeout(timer);
  },[attempt?.submitted_at,busy,confirming,dirty,expired,paused,saving,write]);
  useEffect(()=>{
    if(!dirty||attempt?.submitted_at)return;
    const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};
    window.addEventListener('beforeunload',warn);
    return()=>window.removeEventListener('beforeunload',warn);
  },[dirty,attempt?.submitted_at]);

  function blankDraft(){
    setEditing(true);setEditId('');setPreviousId('');setTitle('');setQuestions([emptyQuestion()]);setRules(defaultRules);setGrading(null);
  }
  function edit(assignment:Assignment,newVersion:boolean){
    void act(async()=>{
      const data=await call<Assignment & {questions:Question[]}>(`/assignments/${assignment.id}?manage=true`);
      setEditing(true);setGrading(null);setTitle(data.title);setQuestions(data.questions);setRules(data.rules);
      setEditId(newVersion?'':data.id);setPreviousId(newVersion?data.id:'');
    });
  }
  function changeQuestion(index:number,change:Partial<Question>){
    setQuestions(rows=>rows.map((q,i)=>i===index?{...q,...change}:q));
  }
  function generate(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    const fields=new FormData(e.currentTarget);
    void act(async()=>{
      const result=await call<{questions:Question[]}>(`/classes/${classId}/generate`,jsonBody({
        count:Number(fields.get('count')), total_marks:Number(fields.get('total'))||null,
        subject_code:String(fields.get('subject')||''), topic:String(fields.get('topic')||''), difficulty:String(fields.get('difficulty')||''),
      }));
      setQuestions(result.questions);
    });
  }
  function importDocument(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    const file=new FormData(e.currentTarget).get('document');
    if(!(file instanceof File)||!file.size)return;
    void act(async()=>{
      const mime = file.type || ({pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png'} as Record<string,string>)[file.name.split('.').at(-1)?.toLowerCase()||''];
      const result=await call<{questions:Question[]}>(`/classes/${classId}/document-import`,{method:'POST',body:file,headers:{'Content-Type':mime||'application/octet-stream'}});
      setQuestions(result.questions);
    },'Review extracted text, options and marks. Diagrams and original formatting may need manual reference.');
  }
  function split(index:number,offset:number){
    const {text}=questions[index];
    const left=text.slice(0,offset).trim(),right=text.slice(offset).trim();
    if(!left||!right){setError(t('Place the cursor between two nonempty sections.'));return;}
    setQuestions(items=>[...items.slice(0,index),{...emptyQuestion(),text:left},{...emptyQuestion(),text:right},...items.slice(index+1)]);
  }
  function merge(index:number){
    const [first,second]=questions.slice(index,index+2);
    const text=first.text+'\n'+second.text, marks=first.marks+second.marks;
    if(text.length>8000||marks>100){setError(t('Merged question exceeds the text or marks limit.'));return;}
    setQuestions(items=>[...items.slice(0,index),{...emptyQuestion(),text,marks},...items.slice(index+2)]);
  }
  function saveAssignment(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    void act(async()=>{
      await call(editId?`/assignments/${editId}`:`/classes/${classId}/assignments`,jsonBody({title,rules,questions,previous_id:previousId||null},editId?'PUT':'POST'));
      setEditing(false);await loadList();
    },'Assignment draft saved.');
  }
  function publish(assignment:Assignment){
    void act(async()=>{
      await call(`/assignments/${assignment.id}/publish`,jsonBody({}));setPendingPublish('');await loadList();
    },'Assignment published.');
  }
  async function loadGrading(assignment:Assignment){
    const [data,results]=await Promise.all([
      call<{questions:Question[]}>(`/assignments/${assignment.id}?manage=true`),
      call<{submissions:Submission[]}>(`/assignments/${assignment.id}/submissions`),
    ]);
    setGrading({assignment,questions:data.questions,rows:results.submissions});setEditing(false);
  }
  function grade(e:FormEvent<HTMLFormElement>,row:Submission,index:number){
    e.preventDefault();
    if(!grading)return;
    const {assignment}=grading, fields=new FormData(e.currentTarget);
    void act(async()=>{
      await call(`/assignments/${assignment.id}/submissions/${row.id}/grades/${index}`,jsonBody({marks:Number(fields.get('marks')),feedback:String(fields.get('feedback')||'')},'PUT'));
      await loadGrading(assignment);
    },'Grade saved.');
  }
  function openByCode(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    void act(async()=>{
      const found=await call<Assignment>('/assignment-code',jsonBody({code}));
      await loadStudent(found.id);setCode('');
    });
  }
  function metrics(value:Metrics){
    return <p>{t('Marks')} {value.marks}/{value.available_marks} · {t('Total marks')} {value.total_marks} · {t('Accuracy')} {value.accuracy??'—'}% · {t('Score percentage')} {value.percentage??'—'}% · {t('Pending review')} {value.pending}</p>;
  }
  function percent(value:number|null){return value===null?'—':new Intl.NumberFormat(lang,{style:'percent',maximumFractionDigits:2}).format(value/100);}
  const question=attempt?.questions[position];
  const done=attempt?.questions.filter(q=>answered(draft[q.position])).length||0;
  function changeAnswer(index:number,value:string|string[]){setDraft(old=>({...old,[index]:value}));}

  return <>
    <section className="work-panel">
      <h2>{t('Assignments')}</h2>
      {error&&<p className="classroom-error" role="alert">{localizedStatus(lang,error)}</p>}
      {(busy||saving)&&<p role="status">{t(saving?'Saving…':'Loading…')}</p>}
      {notice&&<p role="status">{t(notice)}</p>}
      <form onSubmit={openByCode}><div className="work-actions">
        <label>{t('Assignment code')}<input value={code} onChange={e=>setCode(e.target.value)} required maxLength={32}/></label><button disabled={busy||saving}>{t('Find assignment by code')}</button>
      </div></form>
      {classId&&<>
        {!assignments.length&&<p>{t('No assignments yet.')}</p>}
        {manage&&<div><button type="button" onClick={blankDraft}>{t('Create assignment')}</button></div>}
        {assignments.map(assignment=><div className="classroom-row" key={assignment.id}>
          <strong>{assignment.title}</strong><span>{t('Version')} {assignment.version} · {t(!assignment.published_at?'Draft':assignment.published_at>Date.now()/1000?'Scheduled':'Published')}</span>
          {manage?assignment.published_at?<><span>{t('Assignment code')} <code>{assignment.code}</code></span>
            <a href={`/?assignment=${assignment.id}`}>{t('Shareable link')}</a>
            <button disabled={busy} onClick={()=>edit(assignment,true)}>{t('Create new version')}</button>
            <button disabled={busy} onClick={()=>void act(()=>loadGrading(assignment))}>{t('Review submissions')}</button>
          </>:<><button disabled={busy} onClick={()=>edit(assignment,false)}>{t('Edit draft')}</button>
            {pendingPublish===assignment.id?<><span>{t('Publish this version?')}</span><button disabled={busy} onClick={()=>publish(assignment)}>{t('Confirm publication')}</button><button onClick={()=>setPendingPublish('')}>{t('Cancel')}</button></>:
              <button disabled={busy} onClick={()=>setPendingPublish(assignment.id)}>{t('Publish')}</button>}</>:
            <button disabled={busy||saving} onClick={()=>void act(()=>loadStudent(assignment.id))}>{t('Open assignment')}</button>}
        </div>)}
      </>}
    </section>

    {manage&&editing&&<section className="work-panel">
      <h2>{t('Assignment authoring')}</h2>
      <form className="classroom-form" onSubmit={generate}>
        <h3>{t('Question bank')}</h3>
        <div className="classroom-fields">
          <label>{t('Question count')}<input name="count" type="number" defaultValue={5} min={1} max={60} required/></label>
          <label>{t('Total marks')}<input name="total" type="number" min={1} max={300}/></label>
          <label>{t('Subject code')}<input name="subject" maxLength={10}/></label>
          <label>{t('Topic')}<input name="topic" maxLength={100}/></label>
          <label>{t('Difficulty')}<select name="difficulty"><option value="">{t('Any')}</option><option value="easy">{t('Easy')}</option><option value="medium">{t('Medium')}</option><option value="hard">{t('Hard')}</option></select></label>
        </div>
        <div><button disabled={busy}>{t('Generate from bank')}</button></div>
      </form>
      <form className="classroom-form" onSubmit={importDocument}>
        <h3>{t('Import an exam document')}</h3>
        <div className="work-actions"><label>{t('Import file')}<input name="document" type="file" required accept=".pdf,.docx,.jpg,.jpeg,.png"/></label>
          <button disabled={busy}>{t('Import and preview')}</button>
        </div>
      </form>
      <form className="classroom-form" onSubmit={saveAssignment}>
        <label>{t('Assignment title')}<input value={title} required maxLength={100} onChange={e=>setTitle(e.target.value)}/></label>
        <h3>{t('Questions')}</h3>
        {questions.map((q,i)=><fieldset className="classroom-form" key={i}>
          <legend>{i+1}</legend>
          <label>{t('Question text')}<textarea value={q.text} required maxLength={8000} onChange={e=>changeQuestion(i,{text:e.target.value})}/></label>
          <div className="classroom-fields">
            <label>{t('Question type')}<select value={q.kind} onChange={e=>changeQuestion(i,{kind:e.target.value as Kind,accepted:[]})}>
              {Object.entries(typeNames).map(([value,key])=><option key={value} value={value}>{t(key)}</option>)}
            </select></label>
            <label>{t('Marks')}<input type="number" value={q.marks} min={1} max={100} required onChange={e=>changeQuestion(i,{marks:Number(e.target.value)})}/></label>
            <label>{t('Topic')}<input value={q.topic} maxLength={100} onChange={e=>changeQuestion(i,{topic:e.target.value})}/></label>
          </div>
          {(q.kind==='single'||q.kind==='multiple')&&<>
            <label>{t('Options, one per line')}<textarea value={q.options.join('\n')} required onChange={e=>changeQuestion(i,{options:e.target.value.split('\n'),accepted:[]})}/></label>
            <strong>{t('Correct options')}</strong>
            {q.options.map((option,j)=>option.trim()&&<label key={j}><input type={q.kind==='single'?'radio':'checkbox'} name={`correct-${i}`} checked={q.accepted.includes(String(j))} onChange={e=>changeQuestion(i,{accepted:q.kind==='single'?[String(j)]:e.target.checked?[...q.accepted,String(j)]:q.accepted.filter(k=>k!==String(j))})}/>{option}</label>)}
            {q.kind==='multiple'&&<label><input type="checkbox" checked={q.partial_credit} onChange={e=>changeQuestion(i,{partial_credit:e.target.checked})}/>{t('Partial credit')}</label>}
          </>}
          {q.kind==='boolean'&&<label>{t('Correct options')}<select value={q.accepted[0]||''} required onChange={e=>changeQuestion(i,{accepted:[e.target.value]})}>
            <option value=""/><option value="true">{t('True')}</option><option value="false">{t('False')}</option>
          </select></label>}
          {(q.kind==='fill'||q.kind==='number')&&<label>{t('Accepted answers, one per line')}<textarea value={q.accepted.join('\n')} required onChange={e=>changeQuestion(i,{accepted:e.target.value.split('\n')})}/></label>}
          {q.kind==='fill'&&<div className="work-actions">
            <label><input type="checkbox" checked={q.case_sensitive} onChange={e=>changeQuestion(i,{case_sensitive:e.target.checked})}/>{t('Case sensitive')}</label>
            <label><input type="checkbox" checked={q.ignore_punctuation} onChange={e=>changeQuestion(i,{ignore_punctuation:e.target.checked})}/>{t('Ignore punctuation')}</label>
          </div>}
          {q.kind==='number'&&<label>{t('Numerical tolerance')}<input type="number" min={0} step="any" value={q.tolerance} onChange={e=>changeQuestion(i,{tolerance:Number(e.target.value)})}/></label>}
          <div className="work-actions">
            <button type="button" disabled={questions.length>=60} onClick={e=>split(i,e.currentTarget.closest('fieldset')?.querySelector('textarea')?.selectionStart??0)}>{t('Split at cursor')}</button>
            <button type="button" disabled={i===questions.length-1} onClick={()=>merge(i)}>{t('Merge with next')}</button>
            <button type="button" disabled={questions.length===1} onClick={()=>setQuestions(items=>items.filter((_,j)=>i!==j))}>{t('Remove question')}</button>
          </div>
        </fieldset>)}
        <div><button type="button" disabled={questions.length>=60} onClick={()=>setQuestions(items=>[...items,emptyQuestion()])}>{t('Add question')}</button></div>
        <div className="classroom-fields">
          {([['opens_at','Publish at'],['deadline','Deadline']] as const).map(([key,label])=><label key={key}>{t(label)}<input type="datetime-local" value={localDate(rules[key])} onChange={e=>setRules({...rules,[key]:e.target.value?Math.floor(new Date(e.target.value).getTime()/1000):null})}/></label>)}
          <label>{t('Time limit in minutes')}<input type="number" min={1} max={600} value={rules.minutes??''} onChange={e=>setRules({...rules,minutes:Number(e.target.value)||null})}/></label>
          <label>{t('Maximum attempts')}<input type="number" required min={1} max={10} value={rules.attempts} onChange={e=>setRules({...rules,attempts:Number(e.target.value)})}/></label>
        </div>
        <div className="work-actions">{toggles.map(([key,label])=><label key={key}><input type="checkbox" checked={!!rules[key]} onChange={e=>setRules({...rules,[key]:e.target.checked})}/>{t(label)}</label>)}</div>
        <div><button disabled={busy}>{t('Save assignment draft')}</button></div>
      </form>
    </section>}

    {target&&<section className="work-panel">
      <h2>{target.title}</h2>
      {target.rules.deadline&&<p>{t('Deadline')} {new Date(target.rules.deadline*1000).toLocaleString(lang)}</p>}
      <div className="work-actions">
        <button disabled={busy||saving} onClick={()=>void act(async()=>selectAttempt(await call<Attempt>(`/assignments/${target.id}/attempts`,jsonBody({}))))}>{t('Start attempt')}</button>
        {target.rules.leaderboard&&target.rules.show_results&&<button disabled={busy} onClick={()=>void act(async()=>setRanking((await call<{ranking:Ranking[]}>(`/assignments/${target.id}/leaderboard`)).ranking))}>{t('Leaderboard')}</button>}
      </div>
      {attempts.length>0&&<div className="work-actions"><strong>{t('Previous attempts')}</strong>{attempts.map(value=><button key={value.id} disabled={saving} onClick={()=>selectAttempt(value)}>{t('Attempt')} {value.number}</button>)}</div>}
      {attempt&&question&&<>
        <div className="work-actions"><strong>{position+1} / {attempt.questions.length}</strong>
          {attempt.questions.map((q,i)=><button key={q.position} aria-current={position===i?'step':undefined} onClick={()=>setPosition(i)}>{i+1}</button>)}
        </div>
        {!attempt.submitted_at&&remaining!==null&&<p>{expired?t('Time expired'):`${t('Remaining time')} ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}`}</p>}
        <p className="classroom-question">{question.text}</p><p>{t('Marks')} {question.marks}</p>
        <fieldset disabled={!!attempt.submitted_at||expired||confirming}>
          <legend>{t('Your answer')}</legend>
          {(question.kind==='single'||question.kind==='multiple'||question.kind==='boolean')?
            (question.kind==='boolean'?[{id:'true',text:t('True')},{id:'false',text:t('False')}]:question.options).map(option=>{
              const selected=Array.isArray(draft[question.position])?draft[question.position] as string[]:[];
              const multiple=question.kind==='multiple';
              return <label key={option.id}><input type={multiple?'checkbox':'radio'} name={`answer-${question.position}`} checked={multiple?selected.includes(option.id):draft[question.position]===option.id} onChange={e=>changeAnswer(question.position,multiple?(e.target.checked?[...selected,option.id]:selected.filter(value=>value!==option.id)):option.id)}/>{option.text}</label>;
            }):<textarea aria-label={t('Your answer')} maxLength={4000} value={displayAnswer(draft[question.position])} onChange={e=>changeAnswer(question.position,e.target.value)}/>}
        </fieldset>
        <div className="work-actions">
          <button disabled={position===0} onClick={()=>setPosition(position-1)}>{t('Previous')}</button>
          <button disabled={position===attempt.questions.length-1} onClick={()=>setPosition(position+1)}>{t('Next')}</button>
          {!attempt.submitted_at&&<><button disabled={!dirty||saving||expired||confirming} onClick={()=>void write(false)}>{t('Save answers')}</button>
            {paused&&<button disabled={saving} onClick={()=>void act(async()=>{
              const current=await call<Assignment & {attempts:Attempt[]}>(`/assignments/${target.id}`);
              const saved=current.attempts.find(value=>value.id===attempt.id);
              if(saved)selectAttempt(saved);
            })}>{t('Reload saved answers')}</button>}
            <button disabled={saving||expired} onClick={()=>setConfirming(true)}>{t('Submit answers')}</button></>}
        </div>
        {confirming&&<div className="classroom-form">
          <strong>{t('Submit now?')} {t('Answered')} {done} · {t('Unanswered')} {attempt.questions.length-done}</strong>
          <div className="work-actions"><button disabled={saving||expired} onClick={()=>void write(true)}>{t('Confirm submission')}</button><button onClick={()=>setConfirming(false)}>{t('Continue editing')}</button></div>
        </div>}
        {attempt.metrics&&<>{metrics(attempt.metrics)}
          {attempt.grades?.[question.position]&&<p>{t('Marks')} {attempt.grades[question.position].marks??t('Pending review')} · {attempt.grades[question.position].feedback}</p>}
          {question.accepted&&<p>{t('Accepted answers')}: {question.accepted.map(value=>question.options.find(o=>o.id===value)?.text||(question.kind==='boolean'?t(value==='true'?'True':'False'):value)).join(', ')}</p>}
        </>}
      </>}
      {ranking&&<div className="classroom-form"><h3>{t('Leaderboard')}</h3>
        {!ranking.length&&<p>{t('No eligible results yet.')}</p>}
        {ranking.map(row=><div className="classroom-row" key={row.nickname}><strong>{row.rank} · {row.nickname}{row.mine?` (${t('You')})`:''}</strong><span>{row.marks}/{row.total_marks} · {t('Accuracy')} {row.accuracy}%</span></div>)}
      </div>}
    </section>}

    {manage&&grading&&<section className="work-panel">
      <h2>{grading.assignment.title} · {t('Review submissions')}</h2>
      <p>{t('Completed attempts')} {grading.rows.length}</p>
      {!grading.rows.length&&<p>{t('No submissions yet.')}</p>}
      {grading.rows.map(row=><details key={row.id}><summary>{row.username||t('Deleted account')} · {t('Attempt')} {row.number}</summary>
        {metrics(row.metrics)}
        {grading.questions.map((q,i)=><form className="classroom-form" key={i} onSubmit={e=>grade(e,row,i)}>
          <p className="classroom-question">{i+1}. {q.text}</p>
          <p>{t('Your answer')}: {displayAnswer(row.answers[i])||'—'}</p>
          <div className="work-actions">
            <label>{t('Marks')}<input name="marks" type="number" min={0} max={q.marks} step="any" defaultValue={row.grades[i]?.marks??''} required/></label>
            <label>{t('Feedback')}<input name="feedback" maxLength={3000} defaultValue={row.grades[i]?.feedback||''}/></label>
            <button disabled={busy}>{t('Save grade')}</button>
          </div>
        </form>)}
      </details>)}
    </section>}
    {manage&&classId&&<section className="work-panel">
      <h2>{t('Class performance')}</h2>
      <div className="work-actions">
        <label>{t('Period')}<select value={period} onChange={e=>{setPeriod(e.target.value);setAnalytics(null);}}>
          <option value="7">{t('Last 7 days')}</option><option value="30">{t('Last 30 days')}</option><option value="all">{t('All time')}</option>
        </select></label>
        <button disabled={busy} onClick={()=>void act(async()=>setAnalytics(await call<ClassAnalytics>(`/classes/${classId}/analytics?period=${period}`)))}>{t('Load class performance')}</button>
      </div>
      {analytics&&<>
        <p>{t('Active students')} {analytics.students} · {t('Published assignments')} {analytics.published}</p>
        {analytics.assignments.map(row=><details key={row.id}><summary>{row.title}</summary>
          <p>{t('Completion')} {row.completed}/{analytics.students} · {percent(row.completion)}</p>
          <p>{t('Average score percentage')} {percent(row.average_score)} · {t('Average accuracy')} {percent(row.average_accuracy)}</p>
          <h3>{t('Question accuracy')}</h3>
          <ul>{row.questions.map(question=><li key={question.position}>{question.position}. {percent(question.accuracy)} ({question.graded})</li>)}</ul>
        </details>)}
        {analytics.topics.length>0&&<><h3>{t('By topic')}</h3><ul>{analytics.topics.map(topic=><li key={topic.topic}>{topic.topic} · {percent(topic.correct/topic.graded*100)} ({topic.correct}/{topic.graded})</li>)}</ul></>}
      </>}
    </section>}
  </>;
}
