# Architecture / 架构

```text
Your browser → HTTP :3000 → Node / Next.js / React
                                  │ /api/* via loopback
                                  ▼
                         FastAPI :8000 → SQLite + your PDFs
                                  ├─ PyMuPDF: extraction/render/export
                                  ├─ Tesseract: optional local OCR
                                  ├─ Ollama :11434: optional local AI
                                  └─ Optional cloud connection (opt-in)
```

Every installation uses its own data. There is no central account, shared developer backend or developer analytics endpoint.

每次安装使用自己的数据，没有中心账号或开发者托管的后端。

| Path | Purpose / 用途 |
| --- | --- |
| `frontend/app/` | UI, study and editing / 页面、学习与编辑 |
| `frontend/server-lan.cjs` | LAN host validation and normalized proxy headers / 局域网入口 |
| `frontend/next.config.ts` | API rewrite and response headers / 转发与响应头 |
| `backend/app/main.py` | Scanner, imports, catalog and cleanup / 扫描、导入、清理 |
| `backend/app/studio.py` | Accounts, permissions, study and builder / 账号、权限、学习、组卷 |
| `backend/app/question_engine.py` | Draft extraction and original answer references / 拆题及答案引用 |
| `backend/app/security.py` | Request, rendering and storage boundaries / 请求与存储防护 |
| `backend/app/ocr.py`, `layout_edit.py` | OCR and visual revisions / OCR 与编辑撤销 |
| `backend/app/cloud_auth.py` | Experimental per-user cloud connection / 实验性独立云连接 |
| `outputs/start_studio.py` | Detached startup and build snapshot / 后台启动与构建副本 |
| `outputs/https_setup.py`, `frontend/server-https.cjs` | Retained nondefault HTTPS code / 保留的非默认 HTTPS 实现 |
| `backend/scripts/` | Existing optional acceptance scripts / 已有可选验收脚本 |

## Local files / 本机文件

`backend/data/` contains SQLite, uploads, answer images, OCR cache, duplicate recovery and per-user cloud credentials. Credentials are protected by file permissions, **not encrypted at rest**, and excluded from the SQLite backup. `work/runtime/` contains logs, PIDs and the generated host allowlist. `frontend/.studio-runtime/` is a build snapshot. None of these are distributed.

数据目录包含数据库、上传、作答、OCR 缓存、重复回收区和云凭证；凭证仅由文件权限保护，未静态加密，数据库备份不包含凭证。运行记录及构建副本也不会分发。

| Variable | Purpose / 用途 |
| --- | --- |
| `PASTPAPER_DATA_DIR` | Backend data directory; default `backend/data/`. Full Mac launcher assumes the standard layout. / 后端目录，完整启动器仍假定默认布局。 |
| `PASTPAPER_LAN_ONLY=1` | Launcher enables private/local API peer checks. / 启动器启用局域网来源检查。 |
| `PASTPAPER_REQUIRE_HTTPS=0` | Current certificate-free HTTP default. / 当前默认 HTTP。 |
| `PASTPAPER_DIST_DIR` | Launcher-selected frontend snapshot. / 运行副本。 |
| `PASTPAPER_SAMPLE_DIR` | Your own QP/MS fixtures for optional sample checks. / 自己的可选验收材料。 |

Manual backend startup without launcher flags does not have the same deployment protections. Native folder selection and network discovery are macOS-specific.

绕过启动器手动启动时，保护与默认部署不同。文件夹选择与网卡发现依赖 macOS。
