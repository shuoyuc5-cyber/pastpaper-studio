# PastPaper Studio

**Your own past papers. Your own computer. Your own accounts.**

A local Cambridge IGCSE / A Level study workspace built with Next.js, TypeScript, FastAPI, SQLite and PyMuPDF.

[简体中文](README.zh-CN.md) · [Installation / 安装](docs/INSTALLATION.md) · [User guide / 使用](docs/USER_GUIDE.md) · [Architecture / 架构](docs/ARCHITECTURE.md) · [Security / 安全](SECURITY.md)

## Independent installations

This repository distributes **source code**, not a hosted service or a question bank. Each person installs it on their own Mac, creates their own administrator and imports their own PDFs. Their database, passwords, study history and AI connections stay in their installation. There is no connection to the original developer's computer or accounts.

No exam PDFs, personal data, preconfigured users, OAuth credentials, certificates, private keys or models are bundled. Supply materials you are entitled to use. The current interface primarily uses Simplified Chinese; documentation is English-first with Chinese translations.

## Features

| Area | Functionality |
| --- | --- |
| Import | Browser folder import, administrator-selected folder monitoring, progress and errors |
| Catalog | Cambridge filename metadata, QP/MS pairing and original PDF viewing |
| Questions | Draft extraction, local OCR, visual region editing, split/merge and undo |
| Study | Filters, bookmarks, notes, practice sessions, history and conservative scoring |
| Assembly | Draft question selection and reviewed-question PDF export |
| Sharing | Public/private papers within one installation and separate study records |
| Administration | One-use invitations, account suspension and per-user AI permissions |
| Cleanup | Individual/batch duplicate cleanup with original checks and recoverable copies |
| Optional AI | Ollama analysis/embeddings; experimental ChatGPT connection, cloud disabled by default |

Automatic extraction and OCR need human review. Official MS files remain the answer source; AI explanations are separate. ChatGPT availability depends on service/account authorization and is not guaranteed. No paid API-key fallback is included.

## Quick start — macOS

Requires Python 3.11+, Node.js 20+ and npm. Development used Apple Silicon and Python 3.14. The current launcher and native folder picker depend on macOS; Windows/Linux are not supported by these instructions.

Download and extract the repository, or clone it. Run from **inside the project folder**:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
/bin/zsh "outputs/Start PastPaper Studio.command"
```

Open [http://localhost:3000/](http://localhost:3000/) on **your own Mac**. Create the first administrator locally before sharing access, then import your PDFs. A new installation intentionally starts empty.

Scanned PDFs optionally need Tesseract with English/Simplified Chinese data. If Homebrew is installed:

```bash
brew install tesseract tesseract-lang
```

Ollama and models are optional and installed separately. Basic PDF import/viewing does not require AI.

## LAN access and security

Default mode is **certificate-free HTTP on a trusted LAN**, not encrypted HTTPS. Passwords, cookies and documents can be intercepted or modified on an untrusted network. Use a unique password and do not expose port 3000 to the internet. Read [SECURITY.md](SECURITY.md).

To share your installation with your other devices, use the URL printed by **your** launcher. No developer IP address is built into this release. School-managed devices or Wi-Fi client isolation may still block access. Other people installing the source on their own Macs do not need your server running.

## Documentation

- [Installation and troubleshooting / 安装与排错](docs/INSTALLATION.md)
- [User guide / 使用指南](docs/USER_GUIDE.md)
- [Architecture and data / 架构与数据](docs/ARCHITECTURE.md)
- [Status and known limits / 项目状态](docs/STATUS.md)
- [Source packaging / 源码打包](docs/RELEASING.md)
- [Contributing / 参与开发](CONTRIBUTING.md)
- [Third-party notices / 第三方说明](THIRD_PARTY_NOTICES.md)

## Source package

```bash
backend/.venv/bin/python scripts/package_source.py
```

Creates `dist/pastpaper-studio-source.zip`, a manifest and SHA-256 checksum. Explicit source allowlists exclude local data and dependencies. This is **not** a personal-data backup.

## License

GNU Affero General Public License v3.0: [LICENSE](LICENSE). Dependencies retain their own licenses. PyMuPDF/MuPDF offers AGPL or commercial licensing; see [upstream](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). No exam-material redistribution rights are included. This is an independent project, not an official Cambridge product.
