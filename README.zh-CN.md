# PastPaper Studio

**自己的试卷、自己的电脑、自己的账号。**

本地 Cambridge IGCSE / A Level 真题学习工作台，采用 Next.js、TypeScript、FastAPI、SQLite 和 PyMuPDF。

[English](README.md) · [安装](docs/INSTALLATION.md) · [使用指南](docs/USER_GUIDE.md) · [安全说明](SECURITY.md)

## 每个人独立安装

分享的是软件源码，不是开发者的服务器或题库。每个人在自己的 Mac 安装、创建自己的管理员、导入自己的 PDF、连接自己的 AI。各自的数据库、密码、学习记录和 AI 连接互相独立，不访问开发者的电脑。

仓库不包含试卷 PDF、用户数据库、预设账号、OAuth 凭证、证书私钥或模型。请自行提供有权使用的材料。界面目前主要是简体中文，项目文档英文优先并提供中文说明。

## 功能

- 文件夹导入、管理员目录监测、导入进度及错误提示。
- Cambridge 元数据识别、QP/MS 配对、原件逐页浏览。
- 草稿拆题、扫描件 OCR、可视化区域编辑、拆分合并与撤销。
- 筛选、收藏、笔记、在线练习、学习记录及保守评分。
- 组卷草稿、已核对题目的 PDF 导出。
- 本安装内公共/私人题库、独立学习账号、邀请码及账号停用。
- 管理员单个或一键清理重复副本，保留核验过的原件与回收区。
- 可选 Ollama、语义搜索及实验性 ChatGPT 账号连接，云端默认关闭。

OCR 和拆题需要人工核对，官方 MS 是答案来源，AI 分析单独显示。ChatGPT 取决于服务与账号授权，不保证所有账号可用；没有 API Key 或付费 API 自动回退。

## 快速安装：macOS

需要 Python 3.11+、Node.js 20+ 和 npm；开发环境为 Apple Silicon / Python 3.14。启动器及原生文件夹选择依赖 macOS，未提供 Windows/Linux 一键安装。

下载并解压源码，在项目目录内打开终端：

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
/bin/zsh "outputs/Start PastPaper Studio.command"
```

在自己的 Mac 打开 [http://localhost:3000/](http://localhost:3000/)，先创建管理员，再导入自己的 PDF。新安装的题库为空，属于正常情况。

可选扫描件 OCR：已安装 Homebrew 时执行 `brew install tesseract tesseract-lang`，语言包需要 `eng` 和 `chi_sim`。Ollama 及模型另行安装，基础 PDF 功能不依赖 AI。

## 局域网与安全

默认无需证书的 HTTP **不加密传输**，网络中的攻击者可能监听或篡改密码、会话及文档。请使用本网站专用密码，只在可信网络使用，不要映射公网端口。

自己的其他设备使用自己启动器显示的网址，不使用开发者旧 IP。学校设备管理和 Wi-Fi 隔离仍可能阻止互访。其他人在自己电脑安装软件，不需要你的服务器运行。详细边界见 [SECURITY.md](SECURITY.md)。

## 打包与许可

运行 `backend/.venv/bin/python scripts/package_source.py` 可生成不含个人资料的源码 ZIP、清单与校验文件；源码包不是题库备份。

项目采用 GNU AGPL v3.0，见 [LICENSE](LICENSE)，第三方依赖保留各自许可。PyMuPDF/MuPDF 提供 AGPL 或商业许可，见 [维护者说明](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)。不包含 Cambridge 试卷分发权，也不是官方产品。
