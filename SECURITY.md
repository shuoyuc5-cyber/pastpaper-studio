# Security / 安全说明

This is a local Mac study app for small **trusted LANs**, not a hardened public internet service. Default HTTP has no transport encryption or server identity verification. An attacker on the network can read or modify passwords, cookies and documents. School Wi-Fi is not automatically trusted.

本软件面向少量可信局域网用户，未按公网生产服务加固。HTTP 没有传输加密或服务器身份认证，网络攻击者可能读取或篡改密码、会话和文档，学校 Wi-Fi 不应自动视作可信。

Create the administrator locally first, use a unique password, control membership with invitations and do not map ports to the internet. The default launcher does not install certificates, disable the firewall or change system proxies. Trusted HTTPS needs separate deployment work.

先在本机创建管理员，使用专用密码和邀请码，不映射公网端口。默认启动器不安装证书、不关闭防火墙、不修改代理。受信任 HTTPS 需另行部署。

## Controls / 应用保护

- Backend administrator, owner and private-data authorization. / 后端管理员、所属账号及私人资料权限。
- One-use invitations, account suspension and session invalidation. / 邀请码、停用及会话注销。
- Separate ordinary-user AI permissions; no inherited owner cloud account. / AI 权限独立，不继承所有者云账号。
- Salted PBKDF2 password hashes, HttpOnly/SameSite cookies and one-day new sessions. / 密码哈希与会话约束。
- Host/origin checks and normalized forwarded headers. / 主机、来源及代理头校验。
- Bounded bodies/uploads/rendering/storage and in-process rate limits. / 请求、上传、渲染、存储及限流。
- No-store API responses and browser security headers. / API 禁缓存与响应头。
- Verified original preservation during duplicate cleanup. / 重复清理前核验原件。

These controls do not eliminate HTTP interception, provide a complete sandbox for malicious PDFs or stop network-level denial of service. Limits are process-local and reset on restart. Credentials are file-permission protected, not encrypted. Someone controlling the Mac or its system account can access local data.

上述措施不能消除 HTTP 风险、完全隔离恶意 PDF 或阻止网络层攻击；限流重启会重置。凭证未静态加密，控制 Mac 或系统账号的人可读取本机资料。

## Reports / 漏洞报告

Use GitHub private vulnerability reporting if enabled. Otherwise request a private contact method without publishing exploit details. Never attach passwords, cookies, OAuth tokens, database backups, private keys or personal exam files to public issues.

如启用 GitHub 私密漏洞报告，请使用该功能；否则先请求私下联系方式，不公开漏洞细节。不要在公开 Issue 上传任何凭证、数据库、私钥或私人试卷。

## Publication / 发布

The source packager uses an explicit allowlist and excludes data, PDFs, credentials, certificates, logs, caches, models and installed dependencies. Review source changes before publishing; never share your whole running installation as a source package.

源码包用白名单排除上述运行资料。发布前仍须审查源码，不要将整个运行安装目录当源码分享。
