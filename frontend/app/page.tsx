"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PDFPageViewer from "./PDFPageViewer";
import AuthGate from "./AuthGate";
import StudioWorkspace from "./StudioWorkspace";
import AIStatus from "./AIStatus";
import { User } from "./api";

type Paper = {
  id: string;
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

function formatTime(value: string | null | undefined) {
  if (!value) return "尚未扫描";
  const date = new Date(value);
  return date.toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function Home() { return <AuthGate>{(user, logout) => <HomeContent user={user} logout={logout}/>}</AuthGate>; }

function HomeContent({user,logout}: {user:User;logout:()=>Promise<void>}) {
  const [duplicatesOpen,setDuplicatesOpen]=useState(false);
  const [duplicates,setDuplicates]=useState<{id:string;filename:string;path:string;original_filename:string|null}[]>([]);
  const [duplicateError,setDuplicateError]=useState('');
  const [deleting,setDeleting]=useState('');
  const [confirmDuplicate,setConfirmDuplicate]=useState('');
  const [duplicateNotice,setDuplicateNotice]=useState('');
  const [cleanupProgress,setCleanupProgress]=useState('');
  async function cleanAllDuplicates(){
    const items=[...duplicates];
    setDeleting('all');setConfirmDuplicate('');setDuplicateError('');setDuplicateNotice('');
    let cleaned=0;
    const failures:string[]=[];
    try{
      for(let i=0;i<items.length;i++){
        const item=items[i];setCleanupProgress(`正在清理 ${i+1} / ${items.length}`);
        try{await request(`/api/admin/duplicates/${item.id}`,{method:'DELETE'});cleaned++;setDuplicates(rows=>rows.filter(row=>row.id!==item.id));}
        catch(e){failures.push(`${item.filename}：${e instanceof Error?e.message:'清理失败'}`);}
      }
      setDuplicateNotice(`已清理 ${cleaned} 个重复副本${failures.length?`，${failures.length} 个未清理`:''}。`);
      setDuplicateError(failures.join('；'));
      await refresh();
    }finally{setDeleting('');setCleanupProgress('');}
  }
  async function openDuplicates(){setDuplicatesOpen(true);setDuplicateNotice('');setDuplicateError('');setConfirmDuplicate('');try{const data=await request<{files:typeof duplicates}>('/api/admin/duplicates');setDuplicates(data.files);}catch(e){setDuplicateError(e instanceof Error?e.message:'读取失败');}}
  async function cleanDuplicate(id:string){setDeleting(id);setDuplicateNotice('');setDuplicateError('');try{await request(`/api/admin/duplicates/${id}`,{method:'DELETE'});setDuplicates(items=>items.filter(item=>item.id!==id));setConfirmDuplicate('');await refresh();}catch(e){setDuplicateError(e instanceof Error?e.message:'清理失败');}finally{setDeleting('');}}
  const [papers, setPapers] = useState<Paper[]>([]);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [folder, setFolder] = useState("");
  const [choosingFolder, setChoosingFolder] = useState(false);
  const [folderError, setFolderError] = useState("");
  const folderInput = useRef<HTMLInputElement>(null);
  const [folderImportProgress, setFolderImportProgress] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [activeNav, setActiveNav] = useState("library");
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
      setError(cause instanceof Error ? cause.message : "无法连接本地服务。请确认后端正在运行。 ");
    } finally {
      setBooting(false);
    }
  }, [filter, query]);

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
      setFolderError(cause instanceof Error ? cause.message : "打开文件夹选择窗口失败");
    } finally { setBusy(false); setChoosingFolder(false); }
  }

  async function scanNow() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request<{ accepted: boolean }>("/api/scan", { method: "POST" });
      setMessage(result.accepted ? "扫描完成，列表已更新。" : "扫描正在进行，完成后列表会自动更新。");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "扫描失败");
    } finally { setBusy(false); }
  }

  async function importFolder(files: File[]) {
    const pdfs = files.filter(file => file.name.toLowerCase().endsWith(".pdf"));
    setFolderError(""); setMessage("");
    if (!pdfs.length) { setFolderError("所选文件夹中没有 PDF，请重新选择。"); return; }
    if (pdfs.length > 100) { setFolderError(`所选文件夹有 ${pdfs.length} 份 PDF；每次最多导入 100 份，请选择较小的子文件夹。`); return; }
    setBusy(true);
    const failures: string[] = [];
    let imported = 0;
    try {
      for (const [index, file] of pdfs.entries()) {
        setFolderImportProgress(`正在导入 ${index + 1} / ${pdfs.length} 份 PDF`);
        try {
          const response = await fetch(`/api/import/upload?filename=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
          if (!response.ok) {
            const body = await response.json().catch(() => null);
            throw new Error(typeof body?.detail === "string" ? body.detail : `请求失败（${response.status}）`);
          }
          imported += 1;
        } catch (cause) {
          failures.push(`${file.webkitRelativePath || file.name}：${cause instanceof Error ? cause.message : "导入失败"}`);
        }
      }
      if (imported) setMessage(`已导入 ${imported} 份 PDF，正在识别与配对。文件保存在本机私人题库。文件夹新增资料后，请再次选择导入。`);
      if (failures.length) setFolderError(failures.join("；"));
      await refresh();
    } finally { setBusy(false); setFolderImportProgress(""); }
  }

  function openViewer(paper: Paper, kind: "qp" | "ms" = "qp") {
    setSelectedPaper(paper);
    setPdfKind(kind);
  }

  const selectedFileId = selectedPaper ? (pdfKind === "qp" ? selectedPaper.qp_id : selectedPaper.ms_id) : null;
  const pairedPercent = totalCount ? Math.round((pairedCount / totalCount) * 100) : 0;
  const latestIssues = summary?.files.filter((file) => ["failed", "needs_review", "duplicate"].includes(file.status)) ?? [];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><span>p</span></div>
          <div><div className="brand-name">PastPaper <b>Studio</b></div><div className="brand-caption">你的本地真题工作台</div></div>
        </div>
        <div className="nav-label">工作空间</div>
        <nav className="main-nav" aria-label="主导航">
          <button className={`nav-item ${activeNav === "library" ? "active" : ""}`} onClick={() => setActiveNav("library")}><Icon name="library"/><span>试卷库</span><span className="nav-count">{totalCount}</span></button>
          <button className={`nav-item ${activeNav === "import" ? "active" : ""}`} onClick={() => setActiveNav("import")}><Icon name="folder"/><span>导入中心</span>{summary?.scan.scanning && <span className="pulse-dot"/>}</button>
          <div className="nav-divider"/>
          {[['questions','search','题目检索'],['practice','book','在线练习'],['builder','spark','智能组卷'],['mistakes','book','错题与收藏'],['analytics','library','学习统计']].map(([key,icon,label])=><button key={key} className={`nav-item ${activeNav===key?'active':''}`} title={label} onClick={()=>setActiveNav(key)}><Icon name={icon}/><span>{label}</span></button>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card"><div className="local-card-icon"><span/></div><div><strong>本地优先</strong><p>文件保存在你的 Mac</p></div></div>
          <button className="nav-item settings-item" onClick={() => setActiveNav("settings")}><Icon name="settings"/><span>设置与存储</span></button>
          <div className="sidebar-version"><span className="online-dot"/> 本地服务 <span className="version">Phase 2–4</span></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>PastPaper Studio</span><span className="crumb-slash">/</span><strong>{{library:'试卷库',import:'导入中心',questions:'题目检索',practice:'在线练习',builder:'智能组卷',mistakes:'错题与收藏',analytics:'学习统计',settings:'设置与 AI'}[activeNav]}</strong></div>
          <div className="topbar-actions">
            <div className="local-status"><span className="online-dot"/> 本地运行</div>
            <AIStatus/>
            <button className="avatar" aria-label="退出账号" title={`${user.username} · 点击退出`} onClick={()=>void logout()}>{user.username.slice(0,1)}</button>
          </div>
        </header>

        {activeNav!=='library'&&activeNav!=='import'&&<StudioWorkspace mode={activeNav} user={user} navigate={setActiveNav}/>}
        {(activeNav==='library'||activeNav==='import')&&<div className="page-content">
          <div className="welcome-row">
            <div>
              <div className="eyebrow"><span className="eyebrow-line"/> PAST PAPER LIBRARY</div>
              <h1>{activeNav === "import" ? "把真题，整理得井井有条。" : "今天，想练哪一份真题？"}</h1>
              <p className="page-subtitle">你的资料在本地安全归档，QP 与官方评分细则自动配对。</p>
            </div>
            <div className="welcome-illustration" aria-hidden="true"><div className="orb orb-one"/><div className="orb orb-two"/><div className="paper-sheet"><div/><div/><div/><div/></div><div className="sparkle s-one">✦</div><div className="sparkle s-two">✧</div></div>
          </div>

          {error && <div className="alert error-alert"><span className="alert-icon">!</span><div><strong>连接或操作遇到问题</strong><p>{error}</p></div><button onClick={() => void refresh()}>重试</button></div>}
          {message && <div className="alert success-alert"><span className="success-check">✓</span><div>{message}</div><button aria-label="关闭" onClick={() => setMessage("")}>×</button></div>}

          <div className="stat-grid">
            <article className="stat-card"><div className="stat-icon violet"><Icon name="library" size={17}/></div><div className="stat-label">已整理试卷</div><div className="stat-bottom"><strong>{booting ? "—" : totalCount}</strong><span>份</span><div className="mini-chart bars-purple"><i/><i/><i/><i/><i/><i/><i/></div></div></article>
            <article className="stat-card"><div className="stat-icon green"><span className="link-icon">↔</span></div><div className="stat-label">QP / MS 已配对</div><div className="stat-bottom"><strong>{booting ? "—" : pairedCount}</strong><span>份</span><span className="stat-note">{pairedPercent}% 完整</span></div><div className="stat-progress"><i style={{ width: `${pairedPercent}%` }}/></div></article>
            <article className="stat-card"><div className="stat-icon blue"><Icon name="folder" size={17}/></div><div className="stat-label">已扫描 PDF</div><div className="stat-bottom"><strong>{booting ? "—" : scannedCount}</strong><span>份文件</span><span className="stat-note">{summary?.scan.scanning ? "正在更新" : "自动监测中"}</span></div></article>
          </div>

          <section className="folder-panel">
            <div className="panel-heading">
              <div className="folder-heading-icon"><Icon name="folder" size={19}/></div>
              <div><h2>你的真题文件夹</h2><p>选择文件夹导入 PDF，或在 Mac 上设置持续监测</p></div>
              <div className={`scan-badge ${summary?.scan.scanning ? "is-scanning" : ""}`}><span className="scan-dot"/>{summary?.scan.scanning ? "正在扫描" : folder ? "文件夹监测已开启" : "等待选择文件夹"}</div>
            </div>
            <div className="folder-controls">
              <div className="selected-folder"><Icon name="folder" size={17}/><div><strong>{folder ? folder.split("/").filter(Boolean).pop() || "Mac" : "选择存放真题的文件夹"}</strong><span>{folderImportProgress || (choosingFolder ? "请在 Mac 弹出的窗口中选择文件夹" : "在浏览器中选择，无需输入路径")}</span></div></div>
              <input hidden type="file" multiple accept=".pdf,application/pdf" aria-label="选择真题文件夹导入" ref={input => { folderInput.current = input; input?.setAttribute("webkitdirectory", ""); }} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ""; if (files.length) void importFolder(files); }}/>
              <button className="button primary-button" disabled={busy} onClick={() => { setFolderError(""); folderInput.current?.click(); }}>{folderImportProgress ? <span className="button-spinner"/> : <Icon name="folder" size={16}/>} {folderImportProgress ? "正在导入…" : "选择文件夹导入"}</button>
              {user.role === 'admin' && <button className="button" disabled={busy} onClick={() => void chooseFolder()}>{choosingFolder ? "等待选择…" : folder ? "更换监测文件夹" : "设置自动监测"}</button>}
              <button className="icon-button" title="立即重新扫描" disabled={busy || summary?.scan.scanning || !folder} onClick={() => void scanNow()}><span className={busy || summary?.scan.scanning ? "spin" : "refresh-glyph"}>↻</span></button>
            </div>
            {folderError && <p className="folder-error" role="alert">{folderError}</p>}
            <p className="folder-help">文件夹导入包含子文件夹中的 PDF，每次最多 100 份；新增文件后需再次导入。设置自动监测后，新增 PDF 会自动加入题库。</p>
            <div className="folder-footer"><span className="folder-path" title={folder}><span className="folder-state-dot"/>{folder || "尚未设置文件夹"}</span><span className="last-scan">上次扫描：{formatTime(summary?.scan.last_scan_at)}</span></div>
          </section>

          <div className="content-grid">
            <section className="papers-panel">
              <div className="section-heading"><div><h2>最近导入</h2><p>浏览已识别的考试试卷与官方评分细则</p></div><button className="text-button" onClick={() => setActiveNav("import")}>导入记录 <span>→</span></button></div>
              <div className="list-toolbar">
                <label className="search-box"><Icon name="search" size={17}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索科目、年份或考季"/><kbd>⌘ K</kbd></label>
                <label className="filter-select"><select aria-label="配对状态筛选" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部试卷</option><option value="paired">已配对</option><option value="qp_only">缺少 MS</option><option value="ms_only">缺少 QP</option></select><Icon name="chevron" size={15}/></label>
              </div>
              <div className="paper-table-wrap">
                <div className="paper-table-head"><span>试卷</span><span>考试信息</span><span>文件</span><span>状态</span><span/></div>
                {booting ? <div className="empty-state"><div className="empty-spinner"/><strong>正在连接本地题库</strong><p>马上就好…</p></div> : papers.length === 0 ? <div className="empty-state"><div className="empty-art"><Icon name="library" size={24}/></div><strong>{folder ? "这里还没有试卷" : "先添加你的真题文件夹"}</strong><p>{folder ? "识别到 PDF 后，试卷会显示在这里。" : "点击“选择文件夹导入”，选中存放 Cambridge 真题的文件夹开始。"}</p></div> : papers.map((paper) => (
                  <article className="paper-row" key={paper.id}>
                    <div className="paper-primary"><div className="subject-avatar">{paper.subject_code.slice(0, 2)}</div><div><div className="paper-title">{paper.subject || "Cambridge IGCSE"} <span className="paper-code">{paper.subject_code}</span></div><div className="paper-subtitle">{paper.qualification}</div></div></div>
                    <div className="exam-meta"><strong>{paper.season} {paper.year}</strong><span>Paper {paper.paper_number}{paper.paper_level ? ` · ${paper.paper_level}` : ""}</span></div>
                    <div className="file-chips"><button className={`file-chip ${paper.qp_id ? "available" : "missing"}`} disabled={!paper.qp_id} onClick={() => openViewer(paper, "qp")}><span>QP</span>{paper.qp_id ? "查看" : "缺失"}</button><button className={`file-chip ${paper.ms_id ? "available" : "missing"}`} disabled={!paper.ms_id} onClick={() => openViewer(paper, "ms")}><span>MS</span>{paper.ms_id ? "查看" : "缺失"}</button></div>
                    <div><span className={`pair-pill ${paper.pair_status === "paired" ? "paired" : "unpaired"}`}><i/>{paper.pair_status === "paired" ? "已配对" : "待配对"}</span></div>
                    <button className="row-open" onClick={() => openViewer(paper, paper.qp_id ? "qp" : "ms")} aria-label="浏览 PDF">↗</button>
                  </article>
                ))}
              </div>
              <div className="table-footer"><span>显示 {papers.length} 份试卷</span><span className="table-local"><i/> 数据仅存储于本机</span></div>
            </section>

            <aside className="right-rail">
              <section className="progress-card">
                <div className="progress-card-top"><div><div className="rail-eyebrow">IMPORT CENTER</div><h3>导入进度</h3></div><div className="progress-icon"><span className={summary?.scan.scanning ? "spin" : ""}>↻</span></div></div>
                <div className="progress-track"><i style={{ width: `${progress}%` }}/></div>
                <div className="progress-details"><span>{summary?.scan.scanning ? `正在检查 ${summary.scan.processed} / ${summary.scan.found} 个文件` : "自动检查文件夹变化"}</span><strong>{summary?.scan.scanning ? `${progress}%` : "实时"}</strong></div>
                <div className="progress-divider"/>
                <div className="import-stats"><div><span className="import-key"><i className="key-green"/>已识别</span><b>{summary?.counts.completed ?? 0}</b></div><div><span className="import-key"><i className="key-amber"/>需检查</span><b>{(summary?.counts.needs_review ?? 0) + (summary?.counts.failed ?? 0)}</b></div></div>
                {summary?.scan.last_scan_error && <div className="inline-error">{summary.scan.last_scan_error}</div>}
              </section>

              <section className="pairing-card"><div className="pairing-head"><div><div className="rail-eyebrow">SMART MATCHING</div><h3>自动配对</h3></div><div className="match-icon">⌘</div></div><p>根据科目代码、考季、年份和 Paper 编号，把 Question Paper 与官方 Mark Scheme 对应起来。</p><div className="match-example"><div className="match-file"><span className="type-tag qp-tag">QP</span><span>0580_s26_qp_11</span></div><div className="match-connector"><i/><i/><i/><i/><i/><i/><i/></div><div className="match-file"><span className="type-tag ms-tag">MS</span><span>0580_s26_ms_11</span></div><div className="match-check">✓</div></div><div className="pairing-foot"><span>{pairedCount} 份配对成功</span><span className="pairing-arrow">↗</span></div></section>

              <section className="issues-card"><div className="issues-head"><h3>需要留意</h3>{user.role==='admin'&&<button className="text-button" onClick={()=>void openDuplicates()}>管理重复文件 · {summary?.counts.duplicate??0}</button>}<span className="issue-count">{latestIssues.length}</span></div>{latestIssues.length === 0 ? <div className="no-issues"><span>✓</span><div><strong>一切正常</strong><p>暂无需要处理的导入记录</p></div></div> : latestIssues.slice(0, 3).map((item) => <div className="issue-row" key={item.id}><span className={`issue-indicator ${item.status}`}/><div className="issue-copy"><strong>{item.filename}</strong><p>{item.error || statusText[item.status]}</p></div>{item.status==='duplicate'&&user.role==='admin'?<button className="text-button" onClick={()=>void openDuplicates()}>重复文件 · 处理</button>:<span className={`issue-status ${item.status}`}>{statusText[item.status]}</span>}</div>)}</section>

              <div className="privacy-note"><span className="shield-icon">⌑</span><p><strong>你的资料留在你的设备</strong><br/>云端 AI 已关闭，PDF 由本机服务读取。</p></div>
            </aside>
          </div>
        </div>
        }<footer className="page-footer"><span>PastPaper Studio <i>·</i> Phase 2–4</span><span>用专注，换进步。</span></footer>
      </section>

      {duplicatesOpen&&<div className="modal-backdrop"><section className="pdf-modal duplicate-manager" role="dialog" aria-modal="true" aria-label="重复文件清理"><header className="pdf-modal-header"><strong>重复文件 · {duplicates.length}</strong><button className="modal-close" aria-label="关闭" disabled={!!deleting} onClick={()=>setDuplicatesOpen(false)}>×</button></header><div className="duplicate-body"><p>仅管理员可以清理。重复副本移入本机回收区；清理前会确认仍有内容相同的已导入原件。</p><div className="work-actions">{confirmDuplicate==='all'?<><span>确认清理全部 {duplicates.length} 个重复副本？原件保留。</span><button disabled={!!deleting} onClick={()=>void cleanAllDuplicates()}>确认清理全部</button><button disabled={!!deleting} onClick={()=>setConfirmDuplicate('')}>取消</button></>:<button disabled={!!deleting||!duplicates.length} onClick={()=>{setConfirmDuplicate('all');setDuplicateNotice('');}}>一键删除所有重复文件</button>}</div>{cleanupProgress&&<p role="status">{cleanupProgress}</p>}{duplicateNotice&&<p role="status">{duplicateNotice}</p>}{duplicateError&&<p className="folder-error" role="alert">{duplicateError}</p>}{!duplicates.length&&<p>暂无可清理的重复文件。</p>}{duplicates.map(item=><section className="work-panel" key={item.id}><strong>{item.filename}</strong><p className="duplicate-path">重复副本：{item.path}</p><p>保留原件：{item.original_filename||'清理时核验可用原件'}</p>{confirmDuplicate===item.id?<div className="work-actions"><span>确认将此重复副本移入回收区？</span><button disabled={!!deleting} onClick={()=>void cleanDuplicate(item.id)}>{deleting===item.id?'正在清理…':'确认删除重复副本'}</button><button disabled={!!deleting} onClick={()=>setConfirmDuplicate('')}>取消</button></div>:<button disabled={!!deleting} onClick={()=>setConfirmDuplicate(item.id)}>删除重复文件</button>}</section>)}</div></section></div>}
      {selectedPaper && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedPaper(null); }}>
        <section className="pdf-modal" role="dialog" aria-modal="true" aria-label="PDF 浏览器">
          <header className="pdf-modal-header"><div className="modal-title-wrap"><div className="modal-file-icon">PDF</div><div><strong>{selectedPaper.subject || "Cambridge IGCSE"} · {selectedPaper.subject_code}</strong><span>{selectedPaper.season} {selectedPaper.year} · Paper {selectedPaper.paper_number}</span></div></div><button className="modal-close" onClick={() => setSelectedPaper(null)} aria-label="关闭">×</button></header>
          <div className="pdf-tabs"><button className={pdfKind === "qp" ? "active" : ""} disabled={!selectedPaper.qp_id} onClick={() => setPdfKind("qp")}><span className="tab-dot qp-dot"/>Question Paper <small>{selectedPaper.qp_filename ? "已导入" : "未导入"}</small></button><button className={pdfKind === "ms" ? "active" : ""} disabled={!selectedPaper.ms_id} onClick={() => setPdfKind("ms")}><span className="tab-dot ms-dot"/>Mark Scheme <small>{selectedPaper.ms_filename ? "已导入" : "未导入"}</small></button></div>
          {selectedFileId ? <PDFPageViewer fileId={selectedFileId}/> : <div className="pdf-canvas"><div className="empty-state"><strong>还没有导入这个文件</strong><p>将 PDF 放入已监测的文件夹后会自动显示。</p></div></div>}
          <div className="pdf-modal-footer"><span><i className="online-dot"/> 文件从本机读取</span><span>{pdfKind === "qp" ? selectedPaper.qp_filename : selectedPaper.ms_filename}</span></div>
        </section>
      </div>}
    </main>
  );
}
