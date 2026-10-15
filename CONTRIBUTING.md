# Contributing / 参与开发

1. Read setup and security docs; work with your own empty database and authorized fixtures. / 使用自己的空数据库和合法样例。
2. Keep original questions, official MS and AI explanations separate. Never invent official marks or silently confirm extracted questions. / 不混淆官方答案与 AI，不杜撰分值或自动冒充核对。
3. Enforce permissions in the backend and keep cloud AI opt-in without implicit paid calls. / 后端校验权限，云端默认关闭，不自动付费调用。
4. Exclude private data and credentials. Update English docs with corresponding Chinese guidance. / 不提交私人资料，文档英文优先并提供中文。
5. Describe data implications and checks actually performed. Build success is not full acceptance. / 说明数据影响与实际检查，构建不等于完整验收。

For UI development, start the backend on `127.0.0.1:8000` and run `npm run dev` inside `frontend/`. This is for your Mac only; use the production launcher for LAN sharing. Submit focused PRs without personal materials. Report vulnerabilities privately per [SECURITY.md](SECURITY.md).

本机开发可手动启动回环后端和前端开发模式；局域网分享用正式启动器。PR 保持范围清晰，安全问题私下报告。
