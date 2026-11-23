# Host setup on macOS / Mac 主机使用指南

## Start and sign in / 启动与登录

After the [installation steps](INSTALLATION.md), double-click **Start PastPaper Studio.command** in the project's outputs folder. The Chinese launcher starts the same application. The Terminal equivalent, from the project folder, is:

```sh
/bin/zsh "outputs/Start PastPaper Studio.command"
```

Open [http://localhost:3000/](http://localhost:3000/) on the host Mac. Use **Host library sign-in / 登录主机题库**. A fresh installation offers **Create host administrator / 创建主机管理员** only at the host's loopback address. Existing installations use their existing account. Administrators can find accounts and the host/database status under **Administration → User Management**. **Settings** also links to User Management.

An existing installation can launch a verified versioned build from its original shortcut. The original data directory and runtime settings stay with the installation. `--status` reports the running release. If an earlier build is still online, relaunch using `--restart` and add `--lan` when LAN access was in use.

首次安装先完成环境安装，再双击启动文件。在 Mac 上打开上述地址，选「登录主机题库」。首次启动时在本机创建管理员。已有题库继续用原账号。管理员可在「管理 → 用户管理」管理账号和查看主机状态。打开「管理角色」，选择「老师」或「学生」，再点「确认更改角色」。

## Allow the local network / 允许同一局域网访问

This upgrade's launcher starts in local-only mode by default. To share with authorized devices on a trusted network, restart explicitly with LAN access:

```sh
/bin/zsh "outputs/Start PastPaper Studio.command" --restart --lan
```

The launcher lists the current LAN addresses when available. Give students the printed IP address URL and their individual accounts. They can open it in a browser on the same network. The frontend listens on port 3000, and the database API stays on the Mac's loopback port 8000. LAN HTTP is unencrypted. Use an isolated, trusted network, especially when entering passwords or submitting graded work.

LAN clients sign in with a registered email and their existing password. On the host Mac, an existing account can use **Use an existing username on this Mac / 在本机使用原有用户名**. An administrator can then open **Administration → User Management → Account settings** to bind an email. New accounts created in this panel require an email. Binding an address leaves the existing account ID, password, role and records in place. Email addresses are unique per installation and case-insensitive. The optional Cloudflare workspace is a separate deployment.

局域网客户端须用登记的邮箱与密码登录。在主机 Mac 上可点「在本机使用原有用户名」，然后进入「管理 → 用户管理」给旧账号绑定邮箱。旧密码、角色和学习记录可以继续使用。

## Import a folder / 导入整个文件夹

Open **导入中心 → 选择文件夹**. Select a folder in the browser picker, review the PDF list, then choose **导入所选 PDF**. Non-PDF files are ignored. Nested folders are included. The progress shows imports, duplicates, failures and remaining files. **重试失败文件** retries only failed entries. **选择单个 PDF** remains available. The native **设置自动监测** option still manages the Host's watched folder. The device workspace also offers folder review and imports its PDFs into the current browser.

本升级分支默认只在 Mac 上开放。要让同一局域网的同学连接，在 Mac 终端运行上面的命令。把启动窗口打印的局域网 IP 网址发给同学。学校设备或 Wi-Fi 的隔离策略可能禁止设备互访。

## Status, stop and restart / 查看、停止与重启

```sh
/bin/zsh "outputs/Start PastPaper Studio.command" --status
/bin/zsh "outputs/Start PastPaper Studio.command" --stop
/bin/zsh "outputs/Start PastPaper Studio.command" --restart
```

Closing the Terminal window leaves the services running. The Mac must stay awake and connected for other devices. Run the same launcher with `--restart --lan` to restart in LAN mode. Status and errors also appear in `work/runtime/frontend.log` and `work/runtime/backend.log`. If a separate program uses the web or backend port, identify it before making changes. The launcher signals only the registered process group that owns a matching listener. If the browser loads stale scripts, rebuild the frontend, restart, and reload.

关闭终端窗口后服务继续运行。Mac 休眠或关机会中断访问。启动失败时先检查两个日志和端口归属。局域网地址变化时重新启动并使用窗口打印的新地址。

## Local network and public hosting / 局域网与公网

The optional Cloudflare device workspace is a separate deployment. It serves reviewed PDF sharing and stores private work on the browser device. Host classrooms, accounts and grading currently use the local host database. Public hosting of those APIs requires its own deployment and security review.

设备端的 Cloudflare 发布和本机教学主机是两套入口。班级、成员和主机账号保存在运行主机的数据库里。公网发布前需独立验收。
