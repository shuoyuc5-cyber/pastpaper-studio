# Installation / 安装

## Independent setup / 独立安装

Download or clone the source into a permanent writable folder on your own Mac. Do not copy someone else's `backend/data/` or `work/`. Install Python 3.11+, Node.js 20+ and npm separately. From the repository root:

下载源码到自己的 Mac，不能复制他人的数据或运行目录。自行安装 Python、Node.js 和 npm，在仓库根目录执行：

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
chmod +x outputs/*.command
/bin/zsh "outputs/Start PastPaper Studio.command"
```

The `chmod` step restores launcher permissions that browser uploads/downloads may omit. After installation, either English or Chinese `.command` launcher can be double-clicked. Both launch the same application. No default account exists. Create the administrator at `http://localhost:3000/` before allowing LAN access. The first account becomes administrator.

`chmod` 步骤恢复网页上传或下载可能丢失的启动权限。安装后可双击中英文任一启动文件，两者启动同一个软件。没有默认账号；先在本机创建管理员，再允许局域网访问。

## Optional dependencies / 可选依赖

OCR needs Tesseract with `eng` and `chi_sim`. With Homebrew installed, run `brew install tesseract tesseract-lang`; check languages with `tesseract --list-langs`. Without OCR, text PDFs still work. OCR can be slow.

扫描件 OCR 需要上述程序和语言包；不安装仍可处理文本 PDF，扫描件可能报告缺少依赖。

Install Ollama separately, run it locally on port 11434 and install your own models. Select a model in app settings. Semantic search requires an embedding-capable model. Cloud connection is experimental, uses your own account, and remains off until enabled with request consent.

Ollama 和模型另行安装，默认端口 11434，在设置中选择。语义搜索需要 embedding 模型。云端连接属实验功能，使用自己的账号，需开启并逐次确认。

## Updating / 更新

After changing source or pulling updates, run `npm ci` and `npm run build` in `frontend/`, then launch again. The launcher copies the build into `.studio-runtime` so rebuilding does not overwrite the running app's chunks. Services continue after closing the launch window; Mac sleep or shutdown interrupts access.

更新后重新安装前端依赖、构建并启动。运行副本避免构建覆盖在线脚本。关闭启动窗口后服务继续运行，Mac 休眠或关机会中断访问。

## LAN and troubleshooting / 局域网与排错

Use the current address printed by your launcher. Devices need a network that permits peer connections. HTTP is unencrypted; use trusted networks only. No certificate installation or firewall/proxy changes occur automatically.

使用自己启动器显示的当前地址，网络需允许设备互访。HTTP 未加密，仅用于可信网络。不会自动安装证书或修改防火墙、代理。

| Issue / 问题 | Action / 处理 |
| --- | --- |
| Missing environment / 缺少环境 | Complete installation and build. / 完成安装与构建。 |
| Port occupied / 端口占用 | Inspect `work/runtime/*.log`; identify the process before stopping it. / 查看日志并确认归属。 |
| Cannot stop older service / 无法停止旧服务 | Run the launcher in your Mac's Terminal. / 在 Mac 自己的终端启动。 |
| Browser exception / 页面异常 | Rebuild, restart and reload. / 重新构建、启动、刷新。 |
| Empty library / 空题库 | Import your own PDFs; this is expected on new installations. / 新安装正常，导入自己的材料。 |
| Missing original / 原件缺失 | Restore the matching QP/MS, never substitute a different exam. / 恢复对应原件。 |
| Managed tablet cannot connect / 学校平板无法访问 | Ask school IT about device and Wi-Fi restrictions. / 联系学校 IT 检查策略。 |
| AI denied / AI 无权限 | Ask your installation's administrator. / 由自己的管理员授权。 |
