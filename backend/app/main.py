from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from functools import lru_cache
from stat import S_ISREG
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from . import studio, public_mode, pdf_sandbox
from .security import BodyLimit, check_pdf_header, check_range, heavy_operation


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PASTPAPER_DATA_DIR", APP_ROOT / "data")).expanduser().resolve()
public_mode.validate_data(DATA_DIR)
DB_PATH = DATA_DIR / "pastpaper_studio.sqlite3"
if public_mode.ORIGIN and DB_PATH.is_file() and DB_PATH.stat().st_size:
    from contextlib import closing
    with closing(sqlite3.connect(DB_PATH.as_uri()+'?mode=ro', uri=True)) as existing:
        try:
            profile = existing.execute("SELECT value FROM settings WHERE key='independent_public_origin'").fetchone()
        except sqlite3.Error as error:
            raise RuntimeError('Public startup refuses databases without an independent profile') from error
        if not profile or profile[0]!=public_mode.ORIGIN:
            raise RuntimeError('Public startup refuses databases from other profiles or origins')
MAX_PDFS_PER_SCAN = 100
DATA_DIR.mkdir(parents=True, exist_ok=True)

SUBJECTS = {
    "0580": "Mathematics",
    "0625": "Physics",
    "0620": "Chemistry",
    "0610": "Biology",
    "0478": "Computer Science",
    "0455": "Economics",
    "0500": "First Language English",
    "0510": "English as a Second Language",
    "0585": "Chinese",
    "9709": "Mathematics",
    "9701": "Chemistry",
    "9702": "Physics",
    "9700": "Biology",
    "9608": "Computer Science",
    "9618": "Computer Science",
    "9708": "Economics",
    "9231": "Further Mathematics",
}
SEASONS = {"m": "February/March", "s": "May/June", "w": "October/November"}
FILENAME_RE = re.compile(
    r"(?P<code>\d{4})[_\-. ](?P<session>[msw]\d{2})[_\-. ](?P<kind>qp|ms)[_\-. ](?P<paper>\d{1,2})(?:[_\-. ]|$)",
    re.IGNORECASE,
)
SCAN_LOCK = threading.Lock()
FOLDER_PICKER_LOCK = threading.Lock()
SCAN_STATE: dict[str, Any] = {
    "scanning": False,
    "last_scan_at": None,
    "last_scan_error": None,
    "found": 0,
    "processed": 0,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_files (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                file_hash TEXT,
                size_bytes INTEGER,
                mtime_ns INTEGER,
                status TEXT NOT NULL,
                error TEXT,
                duplicate_of_id TEXT REFERENCES source_files(id),
                file_type TEXT,
                qualification TEXT,
                subject TEXT,
                subject_code TEXT,
                year INTEGER,
                season TEXT,
                paper_number TEXT,
                paper_level TEXT,
                calculator TEXT,
                pages INTEGER,
                title TEXT,
                metadata_confidence TEXT,
                first_page_text TEXT,
                added_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_source_files_status ON source_files(status);
            CREATE INDEX IF NOT EXISTS idx_source_files_hash ON source_files(file_hash);
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                paper_key TEXT NOT NULL UNIQUE,
                qualification TEXT NOT NULL,
                subject TEXT,
                subject_code TEXT NOT NULL,
                year INTEGER NOT NULL,
                season TEXT NOT NULL,
                paper_number TEXT NOT NULL,
                paper_level TEXT,
                calculator TEXT,
                qp_file_id TEXT REFERENCES source_files(id),
                ms_file_id TEXT REFERENCES source_files(id),
                pair_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_papers_subject_year ON papers(subject_code, year);
            """
        )
        if public_mode.ORIGIN:
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('independent_public_origin',?)", (public_mode.ORIGIN,))
        studio.initialize_db(conn)


def get_folder(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key='source_folder'").fetchone()
    return str(row["value"]) if row else ""


def parse_filename(filename: str) -> dict[str, Any] | None:
    match = FILENAME_RE.search(Path(filename).stem)
    if not match:
        return None
    code = match.group("code")
    session = match.group("session").lower()
    kind = match.group("kind").lower()
    paper_number = match.group("paper")
    session_match = re.fullmatch(r"([msw])(\d{2})", session)
    assert session_match
    season_code, short_year = session_match.groups()
    year = 2000 + int(short_year) if int(short_year) < 80 else 1900 + int(short_year)
    level = None
    calculator = None
    # Cambridge 0580 paper 1/2 are Core and paper 3/4 are Extended in the current syllabus.
    if code == "0580" and paper_number:
        paper_digit = int(paper_number[0])
        level = "Core" if paper_digit in (1, 2) else "Extended" if paper_digit in (3, 4) else None
        calculator = "Non-calculator" if year >= 2025 and paper_digit in (1, 3) else "Calculator" if paper_digit in (1, 2, 3, 4) else None
    return {
        "qualification": "Cambridge International AS & A Level" if code in ('9709','9701','9702','9700','9608','9618','9708','9231') else "Cambridge IGCSE",
        "subject": SUBJECTS.get(code),
        "subject_code": code,
        "year": year,
        "season": SEASONS[season_code],
        "paper_number": paper_number,
        "file_type": "question_paper" if kind == "qp" else "mark_scheme",
        "paper_level": level,
        "calculator": calculator,
        "metadata_confidence": "filename",
    }


def extract_pdf(path: Path) -> tuple[int, str, str]:
    if public_mode.ORIGIN:
        return tuple(pdf_sandbox.run('inspect',str(path),True,inputs=(path,),timeout=125,preserve_ocr=DATA_DIR/'ocr'))
    return pdf_sandbox.inspect_pdf(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as pdf:
        for chunk in iter(lambda: pdf.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_stamp(path: Path) -> tuple[int, int, int, int, int]:
    info=path.lstat()
    if not S_ISREG(info.st_mode):
        raise OSError('Not a regular file')
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns


@lru_cache(maxsize=32768)
def verified_hash(path: Path, stamp: tuple[int, int, int, int, int]) -> str | None:
    digest=sha256_file(path)
    return digest if stamp==file_stamp(path) else None


def _paper_key(meta: dict[str, Any]) -> str:
    return ":".join(
        str(meta[key] or "")
        for key in ("qualification", "subject_code", "year", "season", "paper_number")
    )


def attach_to_paper(conn: sqlite3.Connection, source_id: str, meta: dict[str, Any]) -> None:
    required = (meta.get("subject_code"), meta.get("year"), meta.get("season"), meta.get("paper_number"), meta.get("file_type"))
    if not all(required):
        return
    source_owner = conn.execute("SELECT owner_id FROM source_files WHERE id=?", (source_id,)).fetchone()["owner_id"]
    key = _paper_key(meta)
    existing_owner = conn.execute("SELECT owner_id FROM papers WHERE paper_key=?", (key,)).fetchone()
    if public_mode.ORIGIN or (existing_owner and existing_owner["owner_id"] != source_owner):
        key += ":" + source_owner
    existing = conn.execute("SELECT * FROM papers WHERE paper_key=?", (key,)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO papers
               (id,paper_key,qualification,subject,subject_code,year,season,paper_number,paper_level,calculator,pair_status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, ?,?)""",
            (
                str(uuid.uuid4()), key, meta["qualification"], meta.get("subject"), meta["subject_code"],
                meta["year"], meta["season"], meta["paper_number"], meta.get("paper_level"), meta.get("calculator"),
                "qp_only" if meta["file_type"] == "question_paper" else "ms_only", now_iso(), now_iso(),
            ),
        )
        existing = conn.execute("SELECT * FROM papers WHERE paper_key=?", (key,)).fetchone()
        conn.execute("UPDATE papers SET owner_id=? WHERE id=?", (source_owner, existing["id"]))
    column = "qp_file_id" if meta["file_type"] == "question_paper" else "ms_file_id"
    if existing[column] is None:
        conn.execute(f"UPDATE papers SET {column}=? WHERE id=?", (source_id, existing["id"]))
    updated = conn.execute("SELECT qp_file_id,ms_file_id FROM papers WHERE id=?", (existing["id"],)).fetchone()
    pair_status = "paired" if updated["qp_file_id"] and updated["ms_file_id"] else "qp_only" if updated["qp_file_id"] else "ms_only"
    conn.execute(
        "UPDATE papers SET pair_status=?,updated_at=? WHERE id=?",
        (pair_status, now_iso(), existing["id"]),
    )


def _scan_paths(folder: Path) -> list[Path]:
    found: list[Path] = []
    for current, dirs, files in os.walk(folder):
        dirs[:] = [directory for directory in dirs if not directory.startswith(".")]
        for filename in files:
            if filename.lower().endswith(".pdf"):
                found.append(Path(current) / filename)
    return found


def scan_library(force_retry_failed: bool = False, public_path: Path | None = None) -> dict[str, Any]:
    if not SCAN_LOCK.acquire(blocking=False):
        return {"accepted": False, "message": "扫描正在进行"}
    SCAN_STATE.update(scanning=True, last_scan_error=None, processed=0)
    try:
        with connect() as conn:
            folder_value = "" if public_mode.ORIGIN else get_folder(conn)
        if public_mode.ORIGIN and public_path is None:
            raise ValueError('Public imports use the independent PDF worker.')
        upload_paths = [public_path] if public_path is not None else _scan_paths(DATA_DIR / 'uploads')
        if not folder_value and not upload_paths:
            SCAN_STATE.update(last_scan_error="尚未设置 PDF 文件夹", found=0, last_scan_at=now_iso())
            return {"accepted": True, "found": 0, "processed": 0}
        folder = Path(folder_value).expanduser().resolve() if folder_value else None
        folder_error = None
        if folder and not folder.is_dir():
            folder_error = "已设置的文件夹不可访问，请重新选择"
            if force_retry_failed and not upload_paths:
                raise ValueError(folder_error)
            folder = None
        paths = list(dict.fromkeys((_scan_paths(folder) if folder else []) + upload_paths))
        SCAN_STATE.update(found=len(paths))
        processed = 0
        batch_count = 0
        for path in paths:
            try:
                source_stamp = file_stamp(path)
                resolved = str(path.resolve())
                with connect() as conn:
                    if public_mode.ORIGIN:
                        conn.execute('BEGIN IMMEDIATE')
                    owner_id = studio.path_owner(conn, path)
                    old = conn.execute("SELECT * FROM source_files WHERE path=?", (resolved,)).fetchone()
                    if public_mode.ORIGIN and (not old or old['status'] not in ('waiting','processing')):
                        continue
                    unchanged = old and old["size_bytes"] == source_stamp[2] and old["mtime_ns"] == source_stamp[3]
                    finished_status = old and old["status"] in ("completed", "needs_review", "duplicate")
                    failed_until_manual_retry = old and old["status"] == "failed" and not force_retry_failed
                    if unchanged and (finished_status or failed_until_manual_retry):
                        processed += 1
                        SCAN_STATE["processed"] = processed
                        continue
                    if batch_count >= MAX_PDFS_PER_SCAN:
                        break
                    batch_count += 1
                    source_id = old["id"] if old else str(uuid.uuid4())
                    digest = verified_hash(path, source_stamp)
                    if digest is None:
                        raise ValueError('文件在扫描时发生变化，请重新扫描。')
                    timestamp = now_iso()
                    if old:
                        conn.execute("UPDATE source_files SET status='processing',error=NULL,updated_at=? WHERE id=?", (timestamp, source_id))
                        if old["file_hash"] != digest:
                            # Sharing consent covered the previously approved bytes.
                            pairs = conn.execute(
                                """SELECT id,qp_file_id,ms_file_id FROM papers
                                   WHERE qp_file_id=? OR ms_file_id=?""",
                                (source_id, source_id)).fetchall()
                            for pair in pairs:
                                conn.execute("UPDATE papers SET visibility='private' WHERE id=?", (pair['id'],))
                                conn.execute("UPDATE source_files SET visibility='private' WHERE id IN (?,?)",
                                             (pair['qp_file_id'], pair['ms_file_id']))
                            conn.execute("UPDATE source_files SET visibility='private' WHERE id=?", (source_id,))
                        # Remove a stale link before rebuilding the metadata association.
                        conn.execute("UPDATE papers SET qp_file_id=NULL,updated_at=? WHERE qp_file_id=?", (timestamp, source_id))
                        conn.execute("UPDATE papers SET ms_file_id=NULL,updated_at=? WHERE ms_file_id=?", (timestamp, source_id))
                        conn.execute("DELETE FROM papers WHERE qp_file_id IS NULL AND ms_file_id IS NULL AND NOT EXISTS (SELECT 1 FROM questions WHERE questions.paper_id=papers.id)")
                        conn.execute(
                            """UPDATE papers SET pair_status=CASE
                                   WHEN qp_file_id IS NOT NULL AND ms_file_id IS NOT NULL THEN 'paired'
                                   WHEN qp_file_id IS NOT NULL THEN 'qp_only' ELSE 'ms_only' END,
                                   updated_at=?""",
                            (timestamp,),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO source_files (id,path,filename,size_bytes,mtime_ns,status,added_at,updated_at) VALUES (?,?,?,?,?,'processing',?,?)",
                            (source_id, resolved, path.name, source_stamp[2], source_stamp[3], timestamp, timestamp),
                        )
                    conn.execute("UPDATE source_files SET owner_id=? WHERE id=?", (owner_id, source_id))
                meta = parse_filename(path.name)
                pages, first_text, title = extract_pdf(path)
                if file_stamp(path) != source_stamp:
                    raise ValueError('文件在扫描时发生变化，请重新扫描。')
                with connect() as conn:
                    duplicate = None
                    for candidate in conn.execute("""SELECT id,path FROM source_files WHERE file_hash=? AND id<>? AND owner_id=?
                        AND status IN ('completed','needs_review','duplicate') ORDER BY status='duplicate',added_at,id""",
                        (digest,source_id,owner_id)):
                        other=Path(candidate['path'])
                        try:
                            stamp=file_stamp(other)
                            if stamp[:2]!=source_stamp[:2] and stamp[2]==source_stamp[2] and verified_hash(other,stamp)==digest:
                                duplicate=candidate
                                break
                        except OSError:
                            continue
                    status = "duplicate" if duplicate else "completed" if meta else "needs_review"
                    error = f"与已导入文件重复（ID {duplicate['id'][:8]}）" if duplicate else None
                    if not meta and not duplicate:
                        # The original PDF remains available even when its filename cannot be interpreted.
                        title = title or path.stem
                        error = "无法从文件名识别 Cambridge 试卷信息；请人工检查文件名格式"
                    values = meta or {}
                    conn.execute(
                        """UPDATE source_files SET file_hash=?,size_bytes=?,mtime_ns=?,status=?,error=?,duplicate_of_id=?,
                           file_type=?,qualification=?,subject=?,subject_code=?,year=?,season=?,paper_number=?,paper_level=?,calculator=?,
                           pages=?,title=?,metadata_confidence=?,first_page_text=?,updated_at=? WHERE id=?""",
                        (
                            digest, source_stamp[2], source_stamp[3], status, error, duplicate["id"] if duplicate else None,
                            values.get("file_type"), values.get("qualification"), values.get("subject"), values.get("subject_code"),
                            values.get("year"), values.get("season"), values.get("paper_number"), values.get("paper_level"),
                            values.get("calculator"), pages, title, values.get("metadata_confidence"), first_text, now_iso(), source_id,
                        ),
                    )
                    if meta and not duplicate:
                        attach_to_paper(conn, source_id, meta)
                processed += 1
                SCAN_STATE["processed"] = processed
            except Exception as exc:
                try:
                    with connect() as conn:
                        conn.execute(
                            """INSERT INTO source_files (id,path,filename,status,error,added_at,updated_at)
                               VALUES (?,?,?,'failed',?,?,?)
                               ON CONFLICT(path) DO UPDATE SET status='failed',error=excluded.error,updated_at=excluded.updated_at
                               WHERE source_files.status<>'cancelled'""",
                            (str(uuid.uuid4()), str(path.resolve()), path.name,
                             'PDF could not be processed.' if public_mode.ORIGIN else str(exc), now_iso(), now_iso()),
                        )
                except Exception:
                    pass
                processed += 1
                SCAN_STATE["processed"] = processed
        SCAN_STATE.update(last_scan_at=now_iso(), last_scan_error=folder_error)
        return {"accepted": True, "found": len(paths), "processed": processed}
    except Exception as exc:
        SCAN_STATE.update(last_scan_error=str(exc), last_scan_at=now_iso())
        raise
    finally:
        SCAN_STATE["scanning"] = False
        SCAN_LOCK.release()


async def background_scanner() -> None:
    while True:
        await asyncio.sleep(8)
        try:
            with connect() as conn:
                folder = "" if public_mode.ORIGIN else get_folder(conn)
            if folder and not SCAN_STATE["scanning"]:
                await asyncio.to_thread(scan_library)
            elif not SCAN_STATE['scanning'] and (DATA_DIR / 'uploads').exists():
                await asyncio.to_thread(scan_library)
            await asyncio.to_thread(studio.index_catalog)
        except Exception:
            # Scan errors are retained in SCAN_STATE and shown in the import center.
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    if public_mode.ORIGIN:
        studio.public_accounts.totp_secret()
        studio.public_accounts.public_mail.settings()
    init_db()
    tasks = [asyncio.create_task(background_scanner())] if not public_mode.ORIGIN else []
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="PastPaper Studio API", version="0.1.0", lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, _error: RequestValidationError):
    detail = ('Check the format and required fields.' if request.headers.get('x-studio-language')=='en'
              else '请求格式不正确，请核对字段和长度。')
    return JSONResponse({'detail':detail},status_code=422)

app.add_middleware(BodyLimit)
if not public_mode.ORIGIN:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )


class FolderRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


@app.get("/api/health")
def health() -> dict[str, str]:
    if public_mode.ORIGIN:
        try:
            with connect() as conn:
                if not conn.execute("SELECT 1 FROM settings WHERE key='independent_public_origin'").fetchone():
                    raise HTTPException(503, 'Database is unavailable')
        except sqlite3.Error as exc:
            raise HTTPException(503, 'Database is unavailable') from exc
    return {"status": "ok", "service": "PastPaper Studio API"}


@app.get("/api/settings")
def settings(request: Request) -> dict[str, Any]:
    with connect() as conn:
        folder = "" if public_mode.ORIGIN else get_folder(conn)
        state = (dict(SCAN_STATE) if not public_mode.ORIGIN else
                 {"scanning":False,"last_scan_at":None,"last_scan_error":None,"processed":0,"found":0})
    return {"public_mode": bool(public_mode.ORIGIN), "source_folder": folder if studio.user(request)['role']=='admin' else '', "scan": state, "cloud_ai": "off"}


@app.put("/api/settings/source-folder")
def set_source_folder(body: FolderRequest) -> dict[str, Any]:
    folder = Path(body.path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail="此文件夹不可访问，请重新选择文件夹。")
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('source_folder',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(folder),),
        )
    # Scan immediately so the user sees files without waiting for the background poll.
    threading.Thread(target=scan_library, daemon=True).start()
    return {"source_folder": str(folder), "message": "文件夹已保存，正在扫描 PDF。"}


@app.post("/api/settings/select-folder")
def select_source_folder() -> dict[str, Any]:
    """Select on the server Mac so the scanner can retain a real local path."""
    if sys.platform != "darwin":
        raise HTTPException(status_code=400, detail="请在运行服务的 Mac 上选择文件夹。")
    if not FOLDER_PICKER_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="文件夹选择窗口已打开，请在 Mac 上完成选择。")
    try:
        # Standard Additions owns this dialog; sending it to Finder adds an unnecessary Automation permission.
        script = '''set selectedFolder to choose folder with prompt "选择存放真题 PDF 的文件夹（包含子文件夹）"
return POSIX path of selectedFolder'''
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=408, detail="选择窗口等待超时，请重新点击选择文件夹。") from exc
        if result.returncode != 0:
            if "(-128)" in result.stderr:
                return {"cancelled": True}
            raise HTTPException(status_code=503, detail="Mac 文件夹选择窗口无法打开，请使用“选择文件夹导入”。如需持续监测，请在 Mac 上双击启动文件后重试。")
        path = result.stdout.strip()
        if not path:
            return {"cancelled": True}
        return {"cancelled": False, **set_source_folder(FolderRequest(path=path))}
    finally:
        FOLDER_PICKER_LOCK.release()


@app.post("/api/scan")
async def rescan() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(scan_library, True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/imports")
def imports(request: Request, limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    owner_id = studio.user(request)['id']
    with connect() as conn:
        counts = {row["status"]: row["count"] for row in conn.execute("SELECT status,COUNT(*) AS count FROM source_files WHERE owner_id=? AND status<>'deleted' GROUP BY status", (owner_id,))}
        rows = conn.execute(
            """SELECT id,filename,status,error,updated_at,file_type,subject_code,year,season,paper_number
               FROM source_files WHERE owner_id=? AND status<>'deleted' ORDER BY updated_at DESC LIMIT ?""",
            (owner_id, limit),
        ).fetchall()
        total_papers = conn.execute("SELECT COUNT(*) FROM papers WHERE owner_id=? OR visibility='public'", (owner_id,)).fetchone()[0]
        paired = conn.execute("SELECT COUNT(*) FROM papers WHERE pair_status='paired' AND (owner_id=? OR visibility='public')", (owner_id,)).fetchone()[0]
    return {
        "counts": counts,
        "total_files": sum(counts.values()),
        "total_papers": total_papers,
        "paired_papers": paired,
        "scan": ({"scanning":bool(counts.get('waiting') or counts.get('processing')),
                  "processed":sum(counts.get(key,0) for key in ('completed','duplicate','failed','needs_review')),
                  "found":sum(counts.values()), "last_scan_at":rows[0]["updated_at"] if rows else None,
                  "last_scan_error":None} if public_mode.ORIGIN else dict(SCAN_STATE)),
        "files": [dict(row) for row in rows],
    }


def duplicate_groups(conn: sqlite3.Connection, owner_id: str) -> list[dict]:
    """Reconcile old duplicate flags with the current files and return verified groups."""
    rows=conn.execute("""SELECT f.*,
        EXISTS (SELECT 1 FROM papers WHERE qp_file_id=f.id OR ms_file_id=f.id) AS linked
        FROM source_files f WHERE f.owner_id=? AND f.status IN ('completed','needs_review','duplicate','missing')
        ORDER BY linked DESC, f.status='duplicate', f.added_at, f.id""",(owner_id,)).fetchall()
    by_size=defaultdict(list)
    missing=[]
    for row in rows:
        path=Path(row['path'])
        try:
            stamp=file_stamp(path)
        except FileNotFoundError:
            if row['status']=='duplicate':
                missing.append(row['id'])
        except OSError:
            continue
        else:
            by_size[stamp[2]].append((row,path,stamp))
    grouped=defaultdict(list)
    for candidates in by_size.values():
        for row,path,stamp in candidates:
            try:
                digest=verified_hash(path,stamp) if len(candidates)>1 else row['file_hash']
            except OSError:
                continue
            if len(candidates)>1 and digest is None:
                continue
            grouped[(digest or row['id'],stamp[2])].append((row,stamp))

    groups=[]
    for (digest,_),members in grouped.items():
        unique={}
        for row,stamp in members:
            unique.setdefault(stamp[:2],row)
        copies=list(unique.values())
        original=copies[0]
        removable=[]
        for row,stamp in members:
            is_copy=(
                len(copies)>1 and row['id']!=original['id']
                and unique[stamp[:2]]['id']==row['id'] and not row['linked']
            )
            if is_copy:
                removable.append(row['id'])
                if row['status']!='duplicate' or row['duplicate_of_id']!=original['id'] or row['file_hash']!=digest:
                    conn.execute('UPDATE source_files SET status=?,duplicate_of_id=?,error=?,file_hash=? WHERE id=?',
                        ('duplicate',original['id'],f"与已导入文件重复（ID {original['id'][:8]}）",digest,row['id']))
            elif row['status'] in ('duplicate','missing'):
                status='completed' if row['file_type'] else 'needs_review'
                conn.execute('UPDATE source_files SET status=?,duplicate_of_id=NULL,error=NULL WHERE id=?',(status,row['id']))
                if row['file_type']:
                    attach_to_paper(conn,row['id'],dict(row))
        if len(copies)>1:
            groups.append({'id':original['id'],'size':members[0][1][2],'copies':[
                {**{key:row[key] for key in ('id','filename','path','added_at')},'can_clean':row['id'] in removable}
                for row in copies]})
    if missing:
        conn.executemany("UPDATE source_files SET status='missing',duplicate_of_id=NULL,error=NULL WHERE id=?",
                         [(source_id,) for source_id in missing])
    return groups


@app.get('/api/admin/duplicates')
def duplicates(request:Request):
    owner=studio.admin(request)
    if not SCAN_LOCK.acquire(timeout=20):
        raise HTTPException(423,'扫描仍在进行，等待后可继续清理。')
    try:
        with connect() as conn:
            groups=duplicate_groups(conn,owner['id'])
        return {'groups':groups}
    finally:
        SCAN_LOCK.release()


class DuplicateBatch(BaseModel):
    ids: list[str] = Field(min_length=1,max_length=24)


@app.post('/api/admin/duplicates/clean')
def clean_duplicates(body: DuplicateBatch, request: Request):
    owner=studio.admin(request)
    if not SCAN_LOCK.acquire(timeout=20):
        raise HTTPException(423,'扫描仍在进行，等待后可继续清理。')
    try:
        results=[]
        for source_id in dict.fromkeys(body.ids):
            try:
                clean_duplicate_file(source_id,owner['id'])
            except HTTPException as error:
                results.append({'id':source_id,'error':error.detail})
            else:
                results.append({'id':source_id,'error':None})
        return {'results':results}
    finally:
        SCAN_LOCK.release()


@app.delete('/api/admin/duplicates/{source_id}')
def delete_duplicate(source_id:str,request:Request):
    owner=studio.admin(request)
    if not SCAN_LOCK.acquire(timeout=20):
        raise HTTPException(423,'扫描仍在进行，等待后可继续清理。')
    try:
        clean_duplicate_file(source_id,owner['id'])
        return {'ok':True}
    finally:
        SCAN_LOCK.release()


def clean_duplicate_file(source_id: str, owner_id: str) -> None:
    moved=None
    source=None
    try:
        with connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute("SELECT * FROM source_files WHERE id=? AND owner_id=?",(source_id,owner_id)).fetchone()
            if not row or row['status'] not in ('duplicate','deleted'):
                raise HTTPException(404,'重复记录不存在或不属于你的账号')
            if row['status']=='deleted':
                return
            if conn.execute('SELECT 1 FROM papers WHERE qp_file_id=? OR ms_file_id=?',(source_id,source_id)).fetchone():
                raise HTTPException(409,'该文件正在被试卷引用，不能清理')
            source=Path(row['path'])
            try:
                source_stamp=file_stamp(source)
            except FileNotFoundError:
                conn.execute("UPDATE source_files SET status='deleted',error=NULL,updated_at=? WHERE id=?",(now_iso(),source_id))
                return
            digest=verified_hash(source,source_stamp)
            if digest is None:
                raise HTTPException(409,'文件内容已变化，请重新扫描后处理')
            copies=conn.execute("""SELECT id,path FROM source_files WHERE owner_id=? AND id<>?
                AND status IN ('completed','needs_review') AND (file_hash=? OR id=?)
                ORDER BY id<>?""",
                (owner_id,source_id,digest,row['duplicate_of_id'],row['duplicate_of_id'])).fetchall()
            survivor=None
            for copy in copies:
                other=Path(copy['path'])
                if other.is_file() and not other.is_symlink() and file_stamp(other)[:2]!=file_stamp(source)[:2] and sha256_file(other)==digest:
                    survivor=copy['id']
                    break
            if not survivor:
                raise HTTPException(409,'找不到完整的已导入原件，先恢复原件再清理，避免丢失唯一副本')
            if source.exists():
                if file_stamp(source)!=source_stamp:
                    raise HTTPException(409,'文件内容已变化，请重新扫描后处理')
                trash=DATA_DIR/'duplicate_trash'
                trash.mkdir(mode=0o700,parents=True,exist_ok=True)
                moved=trash/(str(uuid.uuid4())+'.pdf')
                os.replace(source,moved)
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             ('duplicate_trash:'+source_id,str(moved)))
            conn.execute("UPDATE source_files SET duplicate_of_id=? WHERE duplicate_of_id=?",(survivor,source_id))
            conn.execute("UPDATE source_files SET status='deleted',error=NULL,updated_at=? WHERE id=?",(now_iso(),source_id))
    except Exception as exc:
        if moved and moved.exists() and source and not source.exists():
            os.replace(moved,source)
        if isinstance(exc,OSError):
            raise HTTPException(409,'无法移动文件，请检查本机文件权限；不同磁盘上的文件需手动清理') from exc
        raise


@app.get("/api/papers")
def list_papers(request: Request, q: str = Query(default="", max_length=100), status: str = Query(default="all")) -> dict[str, Any]:
    sql = """SELECT p.*, qf.filename AS qp_filename, qf.status AS qp_status, qf.id AS qp_id,
                      mf.filename AS ms_filename, mf.status AS ms_status, mf.id AS ms_id
               FROM papers p
               LEFT JOIN source_files qf ON qf.id=p.qp_file_id
               LEFT JOIN source_files mf ON mf.id=p.ms_file_id"""
    filters: list[str] = ["(p.owner_id=? OR p.visibility='public')"]
    args: list[Any] = [studio.user(request)['id']]
    if q.strip():
        needle = f"%{q.strip()}%"
        filters.append("(p.subject LIKE ? OR p.subject_code LIKE ? OR CAST(p.year AS TEXT) LIKE ? OR p.season LIKE ? OR p.paper_number LIKE ?)")
        args.extend([needle] * 5)
    if status == "paired":
        filters.append("p.pair_status='paired'")
    elif status in ("qp_only", "ms_only"):
        filters.append("p.pair_status=?")
        args.append(status)
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += " ORDER BY p.year DESC,p.subject_code,p.paper_number"
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"papers": [dict(row) for row in rows]}


@app.get("/api/files/{source_id}")
def view_file(source_id: str, request: Request) -> FileResponse:
    check_range(request)
    with connect() as conn:
        row = conn.execute("SELECT path,filename,status FROM source_files WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文件记录不存在")
    path = Path(studio.resolve_source(source_id))
    return FileResponse(path, media_type="application/pdf", filename=row["filename"], content_disposition_type="attachment" if public_mode.ORIGIN else "inline")


@app.get("/api/files/{source_id}/metadata")
def file_metadata(source_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT id,filename,status,error,pages,title,subject,subject_code,year,season,paper_number,file_type,paper_level,calculator FROM source_files WHERE id=?",
            (source_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文件记录不存在")
    return dict(row)


@app.get("/api/files/{source_id}/pages/{page_number}")
def render_pdf_page(source_id: str, page_number: int) -> Response:
    with connect() as conn:
        row = conn.execute("SELECT path FROM source_files WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文件记录不存在")
    path = Path(studio.resolve_source(source_id))
    try:
        with heavy_operation(wait=2):
            image=(pdf_sandbox.run('page',str(path),page_number,inputs=(path,),binary=True)
                   if public_mode.ORIGIN else pdf_sandbox.render_page(path,page_number))
    except (IndexError,pdf_sandbox.PageUnavailable) as exc:
        raise HTTPException(status_code=404, detail="PDF 页码超出范围") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="无法渲染此 PDF，请检查原件。") from exc
    return Response(content=image, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/debug/parse-filename")
def debug_parse_filename(filename: str = Query(min_length=1, max_length=255)) -> dict[str, Any]:
    return {"filename": filename, "metadata": parse_filename(filename)}


studio.install(app, sys.modules[__name__])
