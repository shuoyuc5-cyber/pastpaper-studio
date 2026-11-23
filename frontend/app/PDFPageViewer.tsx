"use client";
import {useStudioText,useStudioStatus} from "./preferences";

import { useEffect, useState } from "react";

type Status = "loading" | "ready" | "error";

export default function PDFPageViewer({ fileId }: { fileId: string }) {
  const tr=useStudioText();
  const statusCopy=useStudioStatus();

  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError("");
    setPageNumber(1);
    setPageCount(0);
    void fetch(`/api/files/${fileId}/metadata`)
      .then(async (response) => {
        if (!response.ok) throw new Error(tr("无法读取 PDF 文件信息"));
        return response.json() as Promise<{ pages: number }>;
      })
      .then((metadata) => {
        if (!cancelled) setPageCount(metadata.pages);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : tr("无法打开此 PDF"));
        setStatus("error");
      });
    return () => { cancelled = true; };
  }, [fileId]);

  const pageImage = `/api/files/${fileId}/pages/${pageNumber}`;

  return (
    <div className="pdf-viewer-shell">
      <div className="pdf-toolbar">
        <div className="pdf-toolbar-label"><span className="toolbar-page-icon">▤</span>{" "+tr("页面预览")}</div>
        <div className="page-controls">
          <button aria-label={tr("上一页")} disabled={status !== "ready" || pageNumber <= 1} onClick={() => setPageNumber((current) => Math.max(1, current - 1))}>‹</button>
          <span>{status === "loading" ? tr("载入中…") : status === "error" ? tr("无法读取") : `${pageNumber} / ${pageCount}`}</span>
          <button aria-label={tr("下一页")} disabled={status !== "ready" || pageNumber >= pageCount} onClick={() => setPageNumber((current) => Math.min(pageCount, current + 1))}>›</button>
        </div>
      </div>
      <div className="pdf-canvas">
        {status === "loading" && <div className="pdf-state"><div className="empty-spinner"/><strong>{tr("正在渲染 PDF")}</strong><p>{tr("文件留在本机处理")}</p></div>}
        {status === "error" && <div className="pdf-state pdf-error"><strong>{tr("无法显示这份 PDF")}</strong><p>{statusCopy(error)}</p></div>}
        {!!pageCount && status !== "error" && <img key={`${fileId}-${pageNumber}`} src={pageImage} className={`pdf-page-image ${status === "ready" ? "visible" : ""}`} alt={tr("第 {0} 页，共 {1} 页",pageNumber,pageCount)} onLoad={() => setStatus("ready")} onError={() => { setError(tr("服务无法渲染这一页")); setStatus("error"); }} />}
      </div>
    </div>
  );
}
