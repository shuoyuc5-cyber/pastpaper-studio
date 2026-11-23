"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import PDFPageViewer from "./PDFPageViewer";
import DuplicateManager from "./DuplicateManager";
import AuthGate from "./AuthGate";
import StudioWorkspace from "./StudioWorkspace";
import AIStatus from "./AIStatus";
import {HeaderLanguageSwitch,PreferenceControls,roleLabel,useStudioPreferences,useStudioText,useStudioStatus} from "./preferences";
import PDFImportPicker, {usePDFImports} from "./PDFImportPicker";
import { User } from "./api";

const UserManagement = dynamic(() => import("./AccountPermissions"));
const Classrooms = dynamic(() => import("./Classrooms"));
type Paper = {
  id: string;
  owner_id: string;
  visibility: "private" | "public";
  qualification: string;
  subject: string | null;
  subject_code: string;
  year: number;
  season: string;
  paper_number: string;
  paper_level: string | null;
  calculator: string | null;
  pair_status: "paired" | "qp_only" | "ms_only";
  qp_filename: string | null;
  qp_id: string | null;
  qp_status: string | null;
  ms_filename: string | null;
  ms_id: string | null;
  ms_status: string | null;
};

type ImportFile = {
  id: string;
  filename: string;
  status: string;
  error: string | null;
  updated_at: string;
  file_type: string | null;
  subject_code: string | null;
  year: number | null;
  season: string | null;
  paper_number: string | null;
};

type ImportSummary = {
  counts: Record<string, number>;
  total_files: number;
  total_papers: number;
  paired_papers: number;
  scan: { scanning: boolean; last_scan_at: string | null; last_scan_error: string | null; found: number; processed: number };
  files: ImportFile[];
};

const statusText: Record<string, string> = {
  completed: "已识别",
  waiting: "等待中",
  processing: "处理中",
  needs_review: "需检查",
  failed: "导入失败",
  duplicate: "重复文件",
  missing: "文件已移走",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

function Icon({ name, size = 18 }: { name: string; size?: number }) {

  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "library") return <svg {...common}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16M8 7h8M8 11h7"/></svg>;
  if (name === "folder") return <svg {...common}><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h5l2 2h8A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/><path d="M3.5 9h17"/></svg>;
  if (name === "search") return <svg {...common}><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/></svg>;
  if (name === "book") return <svg {...common}><path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H20v17H7.5A2.5 2.5 0 0 0 5 21.5z"/><path d="M5 4.5v17M9 7h7M9 11h7"/></svg>;
  if (name === "spark") return <svg {...common}><path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-2-5.8L4 11l6-2.2z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>;
  if (name === "settings") return <svg {...common}><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.1.9-1.1 1.9-1.4-.5a7.9 7.9 0 0 1-1.6.9l-.3 1.5h-2.2l-.3-1.5a7.9 7.9 0 0 1-1.6-.9l-1.4.5-1.1-1.9 1.1-.9a7 7 0 0 1 0-1.9l-1.1-.9 1.1-1.9 1.4.5a7.9 7.9 0 0 1 1.6-.9l.3-1.5h2.2l.3 1.5a7.9 7.9 0 0 1 1.6.9l1.4-.5 1.1 1.9-1.1.9a7 7 0 0 1-.1 1.8z" transform="translate(-2 -1)"/></svg>;
  if (name === "chevron") return <svg {...common}><path d="m8 10 4 4 4-4"/></svg>;
  return <svg {...common}><path d="M12 5v14M5 12h14"/></svg>;
}

function formatTime(value: string | null | undefined, lang: string) {
  if (!value) return lang==="en"?"No scans yet":"尚未扫描";
  const date = new Date(value);
  return date.toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function Home() {
 return <AuthGate>{(user, logout) => <HomeContent user={user} logout={logout}/>}</AuthGate>; }

function HomeContent({user,logout}: {user:User;logout:()=>Promise<void>}) {
  const tr=useStudioText();
  const statusCopy=useStudioStatus();

  const [duplicatesOpen,setDuplicatesOpen]=useState(false);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [folder, setFolder] = useState("");
  const [choosingFolder, setChoosingFolder] = useState(false);
  const [folderError, setFolderError] = useState("");
  const uploader = usePDFImports();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedNav, setActiveNav] = useState(user.role==="admin"?"library":"classrooms");
  const canImport=!user.publicMode||user.role!=='student';
  const activeNav=selectedNav==="users"&&user.role!=="admin"?"classrooms":selectedNav;
  const {lang,theme}=useStudioPreferences();
  const english=lang==='en';
  const copy=(en:string,zh:string)=>english?en:zh;
  useEffect(()=>{
    if(new URLSearchParams(window.location.search).has('assignment'))setActiveNav('classrooms');
  },[]);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [pdfKind, setPdfKind] = useState<"qp" | "ms">("qp");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [booting, setBooting] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [paperData, importData, settingsData] = await Promise.all([
        request<{ papers: Paper[] }>(`/api/papers?q=${encodeURIComponent(query)}&status=${filter}`),
        request<ImportSummary>("/api/imports"),
        request<{ source_folder: string }>("/api/settings"),
      ]);
      setPapers(paperData.papers);
      setSummary(importData);
      setFolder(settingsData.source_folder);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tr("无法连接本地服务。请确认后端正在运行。"));
    } finally {
      setBooting(false);
    }
  }, [filter, query, tr]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => { void refresh(); }, 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const pairedCount = summary?.paired_papers ?? 0;
  const totalCount = summary?.total_papers ?? 0;
  const scannedCount = summary?.total_files ?? 0;
  const progress = useMemo(() => {
    if (!summary?.scan.scanning) return 100;
    return summary.scan.found ? Math.min(95, Math.round((summary.scan.processed / summary.scan.found) * 100)) : 10;
  }, [summary]);

  async function chooseFolder() {

    setBusy(true); setChoosingFolder(true); setFolderError(""); setMessage("");
    try {
      const result = await request<{ cancelled: boolean; source_folder?: string; message?: string }>("/api/settings/select-folder", { method: "POST" });
      if (!result.cancelled) {
        setFolder(result.source_folder ?? "");
        setMessage(result.message ?? "文件夹已选择，正在扫描 PDF。");
        await refresh();
      }
    } catch (cause) {
      setFolderError(cause instanceof Error ? cause.message : tr("打开文件夹选择窗口失败"));
    } finally { setBusy(false); setChoosingFolder(false); }
  }

  async function scanNow() {

    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request<{ accepted: boolean }>("/api/scan", { method: "POST" });
      setMessage(result.accepted ? "扫描完成，列表已更新。" : "扫描正在进行，完成后列表会自动更新。");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tr("扫描失败"));
    } finally { setBusy(false); }
  }



  function openViewer(paper: Paper, kind: "qp" | "ms" = "qp") {

    setPdfError('');
    setSelectedPaper(paper);
    setPdfKind(kind);
  }

  const [pdfAction,setPdfAction]=useState(false);
  const [pdfError,setPdfError]=useState('');
  const selectedFileId = selectedPaper ? (pdfKind === "qp" ? selectedPaper.qp_id : selectedPaper.ms_id) : null;
  async function setShare(){
    if(!selectedPaper||pdfAction)return;
    const shared=selectedPaper.visibility==='public';
    if(!shared&&!confirm(copy('Confirm you have permission to share these PDFs with signed-in site users.', '请确认你有权向此站点的登录用户共享这些 PDF。')))return;
    const visibility=shared?'private':'public';
    setPdfAction(true);setPdfError('');
    try{
      await request('/api/papers/'+selectedPaper.id+'/sharing',{method:'PUT',body:JSON.stringify({visibility,rights_confirmed:!shared})});
      setSelectedPaper({...selectedPaper,visibility});await refresh();
    }catch(e){setPdfError(e instanceof Error?e.message:copy('Sharing could not be updated.','无法更新共享。'));}
    finally{setPdfAction(false);}
  }

  async function replaceSelected(file:File){
    if(!selectedFileId||pdfAction||!confirm(copy('Replace this PDF? Its existing sharing permission will be revoked.', '替换这份 PDF？现有共享权限将撤销。')))return;
    setPdfAction(true);setPdfError('');
    try{
      const response=await fetch('/api/import/'+selectedFileId+'/replace',{method:'PUT',body:file});
      if(!response.ok){
        const body=await response.json().catch(()=>null);
        throw new Error(body?.detail||copy('Could not queue the replacement.','无法将替换加入队列。'));
      }
      setSelectedPaper(null);setActiveNav('import');
      setMessage(copy('Replacement queued. Sharing was revoked.', '已排队替换 PDF，旧共享权限已撤销。'));
      await refresh();
    }catch(e){setPdfError(e instanceof Error?e.message:copy('Could not queue the replacement.','无法将替换加入队列。'));}
    finally{setPdfAction(false);}
  }
  const pairedPercent = totalCount ? Math.round((pairedCount / totalCount) * 100) : 0;
  const latestIssues = summary?.files.filter((file) => ["failed", "needs_review", "duplicate"].includes(file.status)) ?? [];

  return (
    <main className="app-shell" data-theme={theme} lang={english?'en':'zh-CN'}>
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><span>p</span></div>
          <div><div className="brand-name">PastPaper <b>Studio</b></div><div className="brand-caption">{copy('Local study workspace',tr("你的本地真题工作台"))}</div></div>
        </div>
        <div className="nav-label">{copy('Workspace',tr("工作空间"))}</div>
        <nav className="main-nav" aria-label={copy('Main navigation',tr("主导航"))}>
          <button className={`nav-item ${activeNav === "library" ? "active" : ""}`} aria-label={copy('Paper library',tr("试卷库"))} aria-current={activeNav==='library'?'page':undefined} onClick={() => setActiveNav("library")}><Icon name="library"/><span>{copy('Paper library',tr("试卷库"))}</span><span className="nav-count">{totalCount}</span></button>
          {canImport&&<button className={`nav-item ${activeNav === "import" ? "active" : ""}`} aria-label={copy('Import',tr("导入中心"))} aria-current={activeNav==='import'?'page':undefined} onClick={() => setActiveNav("import")}><Icon name="folder"/><span>{copy('Import',tr("导入中心"))}</span>{summary?.scan.scanning && <span className="pulse-dot"/>}</button>}
          <div className="nav-divider"/>
          {[['questions','search','Question search',tr("题目检索")],['practice','book','Practice',tr("在线练习")],['builder','spark','Paper builder',tr("智能组卷")],['classrooms','book',user.role==='student'?'Student dashboard':'Teaching dashboard',user.role==='student'?tr("学生工作台"):tr("教学工作台")],['mistakes','book','Mistakes and saved',tr("错题与收藏")],['analytics','library','Study analytics',tr("学习统计")]].map(([key,icon,en,zh])=><button key={key} className={`nav-item ${activeNav===key?'active':''}`} title={copy(en,zh)} aria-label={copy(en,zh)} aria-current={activeNav===key?'page':undefined} onClick={()=>setActiveNav(key)}><Icon name={icon}/><span>{copy(en,zh)}</span></button>)}
          {user.role==='admin'&&<>
            <div className="nav-divider"/>
            <div className="nav-label admin-nav-label">{copy('Administration',tr("管理"))}</div>
            <button className={`nav-item ${activeNav==='users'?'active':''}`} aria-current={activeNav==='users'?'page':undefined}
              title={copy('User Management',tr("用户管理"))} aria-label={copy('User Management',tr("用户管理"))} onClick={()=>setActiveNav('users')}>
              <Icon name="settings"/><span>{copy('User Management',tr("用户管理"))}</span>
            </button>
          </>}
        </nav>
        <div className="sidebar-bottom">
          <a className="local-card device-nav-link" href="/device/index.html" aria-label={copy('Device workspace',tr("设备端工作区"))}><div className="local-card-icon"><span/></div><div><strong>{copy('Device workspace',tr("设备端工作区"))}</strong><p>{copy('Keep private files on your device',tr("在自己的设备保存私人资料"))}</p></div></a>
          <button className="nav-item settings-item" aria-label={copy('Settings and storage',tr("设置与存储"))} aria-current={activeNav==='settings'?'page':undefined} onClick={() => setActiveNav("settings")}><Icon name="settings"/><span>{copy('Settings and storage',tr("设置与存储"))}</span></button>
          <div className="sidebar-version"><span className="online-dot"/> {copy('Host workspace',tr("主机题库"))} <span className="version">V3</span></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>PastPaper Studio</span><span className="crumb-slash">/</span><strong>{({library:copy('Paper library',tr("试卷库")),import:copy('Import',tr("导入中心")),questions:copy('Question search',tr("题目检索")),practice:copy('Practice',tr("在线练习")),builder:copy('Paper builder',tr("智能组卷")),classrooms:copy('Classes',tr("班级")),mistakes:copy('Mistakes and saved',tr("错题与收藏")),analytics:copy('Study analytics',tr("学习统计")),settings:copy('Settings and AI',tr("设置与 AI")),users:copy('User Management',tr("用户管理"))})[activeNav]}</strong></div>
          <HeaderLanguageSwitch/>
          <div className="topbar-actions">
            <div className="local-status"><span className="online-dot"/> {user.publicMode?copy('Online','在线'):copy('Host online',tr("本地运行"))}</div>
            {!user.publicMode&&<AIStatus english={english}/>}
            <span className="role-pill current-role">{roleLabel(user.role,english)}</span>
            <button className="avatar" aria-label={copy('Sign out',tr("退出账号"))} title={`${user.username} · ${copy('Sign out',tr("点击退出"))}`} onClick={()=>void logout()}>{user.username.slice(0,1)}</button>
          </div>
        </header>

        {activeNav==='classrooms'&&<Classrooms key={user.role} user={user}/>}
        {activeNav==='users'&&user.role==='admin'&&<UserManagement publicMode={user.publicMode}/>}
        {activeNav==='settings'&&<div className="preferences-bar work-actions">
          <PreferenceControls appearanceOnly/>
          {user.role==='admin'&&<button type="button" className="button" onClick={()=>setActiveNav('users')}>{copy('User Management','用户管理')}</button>}
        </div>}
        {activeNav!=='library'&&activeNav!=='import'&&activeNav!=='classrooms'&&activeNav!=='users'&&<StudioWorkspace mode={activeNav} user={user} navigate={setActiveNav}/>}
        {(activeNav==='library'||activeNav==='import')&&<div className="page-content">
          <div className="welcome-row">
            <div className="host-hero-copy">
              <div className="eyebrow"><span className="eyebrow-line"/> PAST PAPER LIBRARY</div>
              <h1>{activeNav === "import" ? tr("把真题，整理得井井有条。") : tr("今天，想练哪一份真题？")}</h1>
              <p className="page-subtitle">{tr("主机题库保留原件，自动配对试卷与官方评分细则。")}</p>
              {activeNav==='library'&&<div className="host-hero-actions"><button className="button primary-button" onClick={()=>setActiveNav('questions')}><Icon name="search" size={16}/>{tr("搜题")}</button><button className="button host-secondary" onClick={()=>setActiveNav('import')}><Icon name="folder" size={16}/>{tr("导入真题")}</button></div>}
            </div>
            <div className="welcome-illustration" aria-hidden="true"><div className="orb orb-one"/><div className="orb orb-two"/><div className="paper-sheet"><div/><div/><div/><div/></div><div className="sparkle s-one">✦</div><div className="sparkle s-two">✧</div></div>
          </div>

          {error && <div className="alert error-alert"><span className="alert-icon">!</span><div><strong>{tr("连接或操作遇到问题")}</strong><p>{statusCopy(error)}</p></div><button onClick={() => void refresh()}>{tr("重试")}</button></div>}
          {message && <div className="alert success-alert"><span className="success-check">✓</span><div>{tr(message)}</div><button aria-label={tr("关闭")} onClick={() => setMessage("")}>×</button></div>}

          <div className="stat-grid">
            <article className="stat-card"><div className="stat-icon violet"><Icon name="library" size={17}/></div><div className="stat-label">{tr("已整理试卷")}</div><div className="stat-bottom"><strong>{booting ? "—" : totalCount}</strong><span>{tr("份")}</span></div></article>
            <article className="stat-card"><div className="stat-icon green"><span className="link-icon">↔</span></div><div className="stat-label">{tr("QP / MS 已配对")}</div><div className="stat-bottom"><strong>{booting ? "—" : pairedCount}</strong><span>{tr("份")}</span><span className="stat-note">{pairedPercent}{tr("% 完整")}</span></div><div className="stat-progress"><i style={{ width: `${pairedPercent}%` }}/></div></article>
            <article className="stat-card"><div className="stat-icon blue"><Icon name="folder" size={17}/></div><div className="stat-label">{tr("已扫描 PDF")}</div><div className="stat-bottom"><strong>{booting ? "—" : scannedCount}</strong><span>{tr("份文件")}</span><span className="stat-note">{summary?.scan.scanning ? tr("正在更新") : tr("自动监测中")}</span></div></article>
          </div>

          {activeNav==='import'&&canImport&&<section className="folder-panel">
            <div className="panel-heading">
              <div className="folder-heading-icon"><Icon name="folder" size={19}/></div>
              <div><h2>{user.publicMode?copy('Import PDF papers','导入 PDF 试卷'):tr("你的真题文件夹")}</h2>
                <p>{user.publicMode?copy('Select files or a folder from this device.','从当前设备选择 PDF 或文件夹。'):tr("选择文件夹导入 PDF，或在 Mac 上设置持续监测")}</p></div>
              <div className={`scan-badge ${summary?.scan.scanning ? "is-scanning" : ""}`}><span className="scan-dot"/>{summary?.scan.scanning ? tr("正在扫描") : folder ? tr("文件夹监测已开启") : tr("等待选择文件夹")}</div>
            </div>
            {!user.publicMode&&<div className="folder-controls">
              <div className="selected-folder"><Icon name="folder" size={17}/><div><strong>{folder ? folder.split("/").filter(Boolean).pop() || "Mac" : tr("选择存放真题的文件夹")}</strong><span>{choosingFolder ? tr("请在 Mac 弹出的窗口中选择文件夹") : tr("在浏览器中选择，无需输入路径")}</span></div></div>
              {!user.publicMode && user.role === 'admin' && <button className="button" disabled={busy} onClick={() => void chooseFolder()}>{choosingFolder ? tr("等待选择…") : folder ? tr("更换监测文件夹") : tr("设置自动监测")}</button>}
              <button className="icon-button" title={tr("立即重新扫描")} disabled={busy || summary?.scan.scanning || !folder} onClick={() => void scanNow()}><span className={busy || summary?.scan.scanning ? "spin" : "refresh-glyph"}>↻</span></button>
            </div>}
            <PDFImportPicker uploader={uploader} disabled={busy} publicMode={user.publicMode}/>
            {folderError && <p className="folder-error" role="alert">{statusCopy(folderError)}</p>}
            {!user.publicMode&&<><p className="folder-help">{tr("可选择整个文件夹，预览后导入其中的 PDF。设置自动监测后，新增 PDF 会自动加入题库。")}</p>
            <div className="folder-footer"><span className="folder-path" title={folder}><span className="folder-state-dot"/>{folder || tr("尚未设置文件夹")}</span><span className="last-scan">{tr("上次扫描：")}{formatTime(summary?.scan.last_scan_at,lang)}</span></div></>}
          </section>}

          <div className="content-grid">
            <section className="papers-panel">
              <div className="section-heading"><div><h2>{tr("最近导入")}</h2><p>{tr("浏览已识别的考试试卷与官方评分细则")}</p></div><button className="text-button" onClick={() => setActiveNav("import")}>{tr("导入记录")+" "}<span>→</span></button></div>
              <div className="list-toolbar">
                <label className="search-box"><Icon name="search" size={17}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("搜索科目、年份或考季")}/><kbd>⌘ K</kbd></label>
                <label className="filter-select"><select aria-label={tr("配对状态筛选")} value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">{tr("全部试卷")}</option><option value="paired">{tr("已配对")}</option><option value="qp_only">{tr("缺少 MS")}</option><option value="ms_only">{tr("缺少 QP")}</option></select><Icon name="chevron" size={15}/></label>
              </div>
              <div className="paper-table-wrap">
                <div className="paper-table-head"><span>{tr("试卷")}</span><span>{tr("考试信息")}</span><span>{tr("文件")}</span><span>{tr("状态")}</span><span/></div>
                {booting ? <div className="empty-state"><div className="empty-spinner"/><strong>{tr("正在连接本地题库")}</strong><p>{tr("马上就好…")}</p></div> : papers.length === 0 ? <div className="empty-state"><div className="empty-art"><Icon name="library" size={24}/></div><strong>{folder ? tr("这里还没有试卷") : tr("先添加你的真题文件夹")}</strong><p>{folder ? tr("识别到 PDF 后，试卷会显示在这里。") : tr("点击“选择文件夹导入”，选中存放 Cambridge 真题的文件夹开始。")}</p></div> : papers.map((paper) => (
                  <article className="paper-row" key={paper.id}>
                    <div className="paper-primary"><div className="subject-avatar">{paper.subject_code.slice(0, 2)}</div><div><div className="paper-title">{paper.subject || "Cambridge IGCSE"} <span className="paper-code">{paper.subject_code}</span></div><div className="paper-subtitle">{paper.qualification}</div></div></div>
                    <div className="exam-meta"><strong>{paper.season} {paper.year}</strong><span>Paper {paper.paper_number}{paper.paper_level ? ` · ${paper.paper_level}` : ""}</span></div>
                    <div className="file-chips"><button className={`file-chip ${paper.qp_id ? "available" : "missing"}`} disabled={!paper.qp_id} onClick={() => openViewer(paper, "qp")}><span>QP</span>{paper.qp_id ? tr("查看") : tr("缺失")}</button><button className={`file-chip ${paper.ms_id ? "available" : "missing"}`} disabled={!paper.ms_id} onClick={() => openViewer(paper, "ms")}><span>MS</span>{paper.ms_id ? tr("查看") : tr("缺失")}</button></div>
                    <div><span className={`pair-pill ${paper.pair_status === "paired" ? "paired" : "unpaired"}`}><i/>{paper.pair_status === "paired" ? tr("已配对") : tr("待配对")}</span></div>
                    <button className="row-open" onClick={() => openViewer(paper, paper.qp_id ? "qp" : "ms")} aria-label={tr("浏览 PDF")}>↗</button>
                  </article>
                ))}
              </div>
              <div className="table-footer"><span>{tr("显示")+" "}{papers.length}{" "+tr("份试卷")}</span><span className="table-local"><i/>{" "+(user.publicMode?copy("Independent site storage","独立站点存储"):tr("数据仅存储于本机"))}</span></div>
            </section>

            <aside className="right-rail">
              <section className="progress-card">
                <div className="progress-card-top"><div><div className="rail-eyebrow">IMPORT CENTER</div><h3>{tr("导入进度")}</h3></div><div className="progress-icon"><span className={summary?.scan.scanning ? "spin" : ""}>↻</span></div></div>
                <div className="progress-track"><i style={{ width: `${progress}%` }}/></div>
                <div className="progress-details"><span>{summary?.scan.scanning ? tr("正在检查 {0} / {1} 个文件",summary.scan.processed,summary.scan.found) : tr("自动检查文件夹变化")}</span><strong>{summary?.scan.scanning ? `${progress}%` : tr("实时")}</strong></div>
                <div className="progress-divider"/>
                <div className="import-stats"><div><span className="import-key"><i className="key-green"/>{tr("已识别")}</span><b>{summary?.counts.completed ?? 0}</b></div><div><span className="import-key"><i className="key-amber"/>{tr("需检查")}</span><b>{(summary?.counts.needs_review ?? 0) + (summary?.counts.failed ?? 0)}</b></div></div>
                {summary?.scan.last_scan_error && <div className="inline-error">{statusCopy(summary.scan.last_scan_error)}</div>}
              </section>

              <section className="pairing-card"><div className="pairing-head"><div><div className="rail-eyebrow">SMART MATCHING</div><h3>{tr("自动配对")}</h3></div><div className="match-icon">⌘</div></div><p>{tr("根据科目代码、考季、年份和 Paper 编号，把 Question Paper 与官方 Mark Scheme 对应起来。")}</p><div className="match-example"><div className="match-file"><span className="type-tag qp-tag">QP</span><span>0580_s26_qp_11</span></div><div className="match-connector"><i/><i/><i/><i/><i/><i/><i/></div><div className="match-file"><span className="type-tag ms-tag">MS</span><span>0580_s26_ms_11</span></div><div className="match-check">✓</div></div><div className="pairing-foot"><span>{pairedCount}{" "+tr("份配对成功")}</span><span className="pairing-arrow">↗</span></div></section>

              <section className="issues-card"><div className="issues-head"><h3>{tr("需要留意")}</h3>{user.role==='admin'&&<button className="text-button" onClick={()=>setDuplicatesOpen(true)}>{copy("Manage duplicate files","管理重复文件")}</button>}<span className="issue-count">{latestIssues.length}</span></div>{latestIssues.length === 0 ? <div className="no-issues"><span>✓</span><div><strong>{tr("一切正常")}</strong><p>{tr("暂无需要处理的导入记录")}</p></div></div> : latestIssues.slice(0, 3).map((item) => <div className="issue-row" key={item.id}><span className={`issue-indicator ${item.status}`}/><div className="issue-copy"><strong>{item.filename}</strong><p>{statusCopy(item.error || statusText[item.status] || item.status)}</p></div>{item.status==='duplicate'&&user.role==='admin'?<button className="text-button" onClick={()=>setDuplicatesOpen(true)}>{tr("重复文件 · 处理")}</button>:<span className={`issue-status ${item.status}`}>{tr(statusText[item.status] || item.status)}</span>}</div>)}</section>

              {!user.publicMode&&<div className="privacy-note"><span className="shield-icon">⌑</span><p><strong>{tr("你的资料留在你的设备")}</strong><br/>{tr("云端 AI 已关闭，PDF 由本机服务读取。")}</p></div>}
            </aside>
          </div>
        </div>
        }<footer className="page-footer"><span>PastPaper Studio <i>·</i> V3</span></footer>
      </section>

      {duplicatesOpen&&user.role==='admin'&&<DuplicateManager onClose={()=>setDuplicatesOpen(false)} onChanged={refresh}/>}
      {selectedPaper && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedPaper(null); }}>
        <section className="pdf-modal" role="dialog" aria-modal="true" aria-label={tr("PDF 浏览器")}>
          <header className="pdf-modal-header"><div className="modal-title-wrap"><div className="modal-file-icon">PDF</div><div><strong>{selectedPaper.subject || "Cambridge IGCSE"} · {selectedPaper.subject_code}</strong><span>{selectedPaper.season} {selectedPaper.year} · Paper {selectedPaper.paper_number}</span></div></div><button className="modal-close" onClick={() => setSelectedPaper(null)} aria-label={tr("关闭")}>×</button></header>
          <div className="pdf-tabs"><button className={pdfKind === "qp" ? "active" : ""} disabled={!selectedPaper.qp_id} onClick={() => setPdfKind("qp")}><span className="tab-dot qp-dot"/>Question Paper <small>{selectedPaper.qp_filename ? tr("已导入") : tr("未导入")}</small></button><button className={pdfKind === "ms" ? "active" : ""} disabled={!selectedPaper.ms_id} onClick={() => setPdfKind("ms")}><span className="tab-dot ms-dot"/>Mark Scheme <small>{selectedPaper.ms_filename ? tr("已导入") : tr("未导入")}</small></button></div>
          {user.publicMode&&selectedPaper.owner_id===user.id&&<div className="pdf-tabs">
            <button disabled={pdfAction} onClick={()=>void setShare()}>{selectedPaper.visibility==='public'?copy('Stop sharing','停止共享'):copy('Share with signed-in users','共享给登录用户')}</button>
            {selectedFileId&&<label>{copy('Replace selected PDF','替换当前 PDF')} <input type="file" accept=".pdf,application/pdf" disabled={pdfAction} onChange={event=>{
              const file=event.target.files?.[0];event.target.value='';if(file)void replaceSelected(file);
            }}/></label>}
            {pdfError&&<span role="alert">{pdfError}</span>}
          </div>}
          {selectedFileId ? <PDFPageViewer fileId={selectedFileId}/> : <div className="pdf-canvas"><div className="empty-state"><strong>{tr("还没有导入这个文件")}</strong><p>{tr("将 PDF 放入已监测的文件夹后会自动显示。")}</p></div></div>}
          <div className="pdf-modal-footer"><span><i className="online-dot"/>{" "+(user.publicMode?copy("File served by this site","文件由此站点提供"):tr("文件从本机读取"))}</span><span>{pdfKind === "qp" ? selectedPaper.qp_filename : selectedPaper.ms_filename}</span></div>
        </section>
      </div>}
    </main>
  );
}
