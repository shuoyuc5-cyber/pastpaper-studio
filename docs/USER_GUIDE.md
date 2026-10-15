# User guide / 使用指南

## Import / 导入

Choose a folder in the browser, up to 100 PDFs per batch. Browser imports store local copies. An administrator may select a Mac directory for ongoing monitoring; the native picker opens on that Mac. Monitored files stay in their original directory.

浏览器每批最多导入 100 份 PDF，保存本机副本；管理员可选择 Mac 目录持续监测，选择窗口在服务器 Mac 打开，原件保持原位置。

Cambridge names such as `0580_s26_qp_11.pdf` / `0580_s26_ms_11.pdf` infer subject, year, session, paper and QP/MS type. Check metadata against originals. These names are examples; no actual samples are bundled.

上述文件名示例可识别考试身份并配对，结果需核对原件；仓库不附带真实样卷。

## Review and study / 核对与学习

Review extracted regions and official MS references before confirming questions. Visual tools support region selection, split/merge and undo. OCR, topic tagging and answer mapping can be wrong. Draft assembly may include pending questions when explicitly selected; PDF export requires reviewed questions. Scoring is conservative, especially for handwriting, diagrams and method marks. AI explanations are never official MS answers.

核对题目区域和 MS 后再确认。可视化支持框选、拆分合并与撤销。OCR、分类、答案对应可能出错；明确选择后草稿可包含待核对题，导出仍要求核对。评分不能替代手写、图形和过程分人工评阅，AI 不是官方答案。

## Accounts and sharing / 账号与共享

First account is administrator. Invitations expire after 24 hours and are single-use. Each user has separate notes and records. Public/private sharing applies **within this installation**, not to GitHub or the internet. Share only materials you have permission to share.

首个账号为管理员；邀请码 24 小时有效、单次使用。笔记和学习记录独立。“公共”仅指本安装内，不代表上传 GitHub 或互联网，分享材料须有授权。

Ordinary users cannot use AI by default. Administrators control local/cloud AI permissions and account suspension. Permitted cloud users connect their own accounts, not the owner's. Basic PDF features do not need AI.

普通账号默认无 AI 权限；管理员可控制权限和启停。获准用户连接自己的云账号，不使用所有者账号，基础 PDF 功能不依赖 AI。

## Duplicate cleanup / 重复清理

Administrators open **需要留意 → 管理重复文件**. Choose individual cleanup or **一键删除所有重复文件**, confirm once and keep the tab open for batch progress. Each item checks ownership, duplicate status, direct paper references, unchanged content and an accessible identical completed original.

管理员进入上述入口，可单个或一键确认清理；批量处理请保持网页打开。每份文件均校验所属账号、重复状态、试卷引用、内容与完整相同原件。

Copies move into `backend/data/duplicate_trash/`; failed items remain with reasons. Scanning activity, cross-volume moves or permissions can prevent cleanup. Recover files manually on the Mac if needed; original paths remain in SQLite. The recovery directory is not automatically emptied.

副本移入本机回收区，不可处理的文件保留并说明原因。扫描、跨磁盘移动或权限可能阻止清理。恢复可在本机人工处理，原路径保留在数据库，回收区不会自动清空。
