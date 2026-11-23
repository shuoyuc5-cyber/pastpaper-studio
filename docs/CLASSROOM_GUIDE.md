# Classroom guide / 班级与作业指南

## Administrator / 管理员

Open **Administration → User Management**. Create a student account with an initial password. Search for the account and use **Manage role → Teacher → Confirm role change**. Use **Manage role → Student → Confirm role change** to restore student access. The role history shows both operations. The server checks the current role on each request.

在「管理 → 用户管理」按邮箱或名称搜索。点「管理角色」，选择「老师」或「学生」，再点「确认更改角色」。

老师可以管理自己创建的班级，管理员可以管理本机账号和班级。老师既可管理自己的班级，也可在其他老师的班级作为学生参加。老师权限不会授予主机 AI、账号管理或备份权限。

If the account owns classes, select an enabled teacher or administrator as the new owner before confirming Student. The successor must have no membership or student work in those classes. Membership, assignments and grades stay with the class.

## Teacher / 老师

1. Go to **班级 / Classes**, create a class, and choose approval or automatic admission. Open **Manage** for the class code, its expiration, member search and approvals. Pause joining or regenerate the code there.
2. In that class, choose **Create assignment**. Add questions manually, generate from permitted confirmed bank questions, or import PDF, DOCX, JPG or PNG into the editable preview. Review the text, marks, choices and keys. The split control uses the text cursor. The merge control combines the current and next question. Both produce drafts that require review.
3. Choose publishing time, deadline, attempt count, time limit, random order and result options. Save the draft, then confirm publication. Give active class members the assignment code or link. Create a new version for changes to a published paper.
4. Use **Review submissions** to give marks and feedback. Use **Class performance** for completion, average score, accuracy, per-question results and topic summaries.

导入主要提取文本、可识别选项和分值。DOCX 的表格单元格文字会按文档顺序提取。复杂数学排版、图片、表格版式和嵌套小题需对照原件人工核对。扫描件和照片依赖本机 Tesseract。导入不会自动生成正确答案。题库组卷将已授权题目的文字和分值复制到草稿，教师可以配置题型与答案。

## Student / 学生

Sign in to the host with the assigned account. Open **班级 / Classes**, preview the class with its class code and join or request admission. Open an assignment from your class, its code or its link. Answer online, review answered and unanswered counts, then confirm submission. The server applies the configured time limit and deadline.

班级成员、答卷、成绩保存在主机数据库。私人 PDF、笔记和个人 AI 仍可在设备端工作区独立使用。作业答卷保存成功后，页面会显示确认。重新打开作业可继续已保存的草稿。服务器发现答卷在其他页面变更时，需要读取保存版本再继续。

## Scoring and results / 评分与结果

Choice, true/false, fill-in and numerical questions use deterministic grading. Multiple choice can subtract incorrect selections from the count of correct selections before awarding a proportional score. Short answers await a teacher. Accuracy is fully correct graded questions divided by graded questions. Score percentage is awarded marks divided by marks available on graded questions. The total available across all questions is also shown while some remain pending. Enabled assignment rankings show pseudonyms, use the best fully graded attempt per student, and rank tied scores and accuracy equally.

The Host and device workspaces support English, Simplified Chinese, Light, Dark and System. Preferences are stored in the browser. Question search keeps its filters, card layout and inline original-paper images.
