# Source releases / 源码发布

Run `backend/.venv/bin/python scripts/package_source.py` from the repository root. Only standard Python modules are needed for this packaging step; a regular `python3` also works.

在仓库根目录运行以上命令即可生成源码包；打包本身仅需 Python 标准库。

## Included / 包含

Application source, frontend lockfile, backend dependency manifests, launch scripts, existing optional acceptance scripts, English-first/Chinese documentation and license. A generated manifest records each source file's SHA-256 and byte count.

包含应用源码、依赖清单、启动器、已有验收脚本、双语文档和许可；清单记录文件大小与 SHA-256。

## Excluded / 不包含

PDFs and screenshots, personal historical development notes, databases and backups, uploads, answer images, cloud credentials, certificates/keys/fingerprints, models, logs/PIDs, runtime host lists, installed dependencies, Python environments, frontend builds, audit tools and the original developer's filesystem paths.

不包含 PDF、截图、个人历史开发记录、数据库及备份、上传和作答、云凭证、证书私钥及指纹、模型、运行记录、依赖环境、构建、审计工具和开发者本机路径。

`dist/pastpaper-studio-source.zip` is for installing a new independent copy, **not** transferring an existing user's data. `dist/SHA256SUMS.txt` checks the ZIP. `dist/SOURCE_MANIFEST.json` lists included source files. For a GitHub upload, publish exactly the source allowlist from `scripts/package_source.py`, not all files in the local workspace.

源码包用于独立新安装，不用于迁移某人的资料。发布到 GitHub 时也只提交同一白名单，不要整个工作目录直接上传。

## Dependencies and checks / 依赖与检查

`frontend/package-lock.json` supports `npm ci`. `backend/requirements.txt` provides supported ranges; `backend/requirements-lock.txt` records the development environment's installed versions. The latter is a reference for the original Mac/Python environment, not a guarantee for every Python/platform combination. No frontend build, model or virtual environment is prepackaged.

前端锁文件用于 `npm ci`。后端范围清单用于常规安装，版本快照用于参考开发环境，不保证所有平台/Python 版本都兼容。源码包不预装构建、模型或虚拟环境。

Packaging checks allowlisted paths and obvious credential patterns. It does not prove the app is vulnerability-free or replace a human review. This publication pass does not run the existing acceptance suites or make live cloud requests.

打包检查白名单路径和明显凭证模式，不等于完整安全审计。本次整理不执行已有验收套件，也不发起真实云调用。

## First use / 首次使用

Extract the source and follow [installation](INSTALLATION.md). Create your own administrator, import your own PDFs and configure optional AI with your own accounts. Never restore the developer's data or connect to the developer's old IP.

解压后按安装指南操作，创建自己的管理员、导入自己的 PDF、连接自己的 AI；不要使用开发者资料和旧 IP。
