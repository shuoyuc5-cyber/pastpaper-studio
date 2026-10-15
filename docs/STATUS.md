# Status / 项目状态

Snapshot: 2026-10-15. An evolving local application, not a fully verified production service.

快照日期 2026-10-15：持续开发的本地软件，不是完整验收的生产服务。

Phase 1 implements PDF imports, metadata, QP/MS pairing, progress and original viewing. Later modules implement OCR, draft extraction/review, region editing, practice, builder/export, account/AI permissions and duplicate cleanup. The sidebar footer remains at the viewport bottom during scrolling.

Phase 1 包含导入、元数据、配对、进度和浏览；后续模块包含 OCR、拆题核对、编辑、练习、组卷、权限和重复清理。侧栏底部区域随视口保持可见。

## Evidence and limits / 检查与限制

- Previous frontend production builds completed. This packaging pass does not claim new full acceptance/security/device/AI testing. / 之前构建通过；本次整理不代表新一轮完整验收。
- Existing assertion-based checks are preserved in `backend/scripts/`; they run only when explicitly invoked. No automated test workflow is installed. / 保留可选验收脚本，不会自动运行，本次未新增测试工作流。
- Original sample PDFs are not bundled. Related checks need your own `0580_s26_qp_11.pdf` and `0580_s26_ms_11.pdf` in `PASTPAPER_SAMPLE_DIR`; exact assertions are sample-specific. / 真实材料需自行提供，精确断言仅适用于对应样卷。
- No live ChatGPT inference/login, managed tablet access, public hosting or full fresh-machine installation is certified by this release. / 不宣称真实云调用、学校平板、公网或全新机器安装已验证。
- OCR, boundaries, topic tagging, answer mapping and scoring need human review. Large PDFs can be slow. / OCR、区域、分类、答案对应及评分需要人工核对。
- Launchers/native folder selection are Mac-specific. The UI primarily uses Simplified Chinese. / 启动器依赖 Mac，界面主要为中文。
- Sharing source does not grant exam-material distribution rights. / 分享源码不包含试卷分发权。

Future directions include broader paper-format coverage, accessibility/languages, trusted HTTPS deployment and improved backup/restore. These are directions, not completed features.

后续方向包括更多试卷格式、无障碍与语言、受信任 HTTPS、备份恢复；不是已完成承诺。
