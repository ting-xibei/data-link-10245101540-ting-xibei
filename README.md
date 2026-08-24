# 数据链软件暑期学校个人实验仓库

本仓库用于个人完成并提交 M1—M6 实践。请保持仓库为私有状态，不要加入其他学生为协作者。

## 开始实验

进入课程包目录，按环境说明建立独立环境：

```powershell
cd summer_school_practice_v1.0
powershell -ExecutionPolicy Bypass -File environment\setup.ps1
```

学生任务入口：`summer_school_practice_v1.0/student_package/README.md`。

## 保存成果

- 程序：`summer_school_practice_v1.0/student_package/src/`，也可以直接完成`src_skeleton/`；
- 结构化结果：`summer_school_practice_v1.0/student_package/output/`；
- 流程图、说明和展示材料：`summer_school_practice_v1.0/student_package/docs/`；
- 综合运行说明：`summer_school_practice_v1.0/student_package/SUBMISSION_README.md`。

完整操作方法见 `summer_school_practice_v1.0/student_package/guides/student_submission_guide.md`。

## 最终检查

在 `summer_school_practice_v1.0/` 目录执行：

```powershell
.\.venv\Scripts\python.exe environment\run_student_checks.py
.\.venv\Scripts\python.exe environment\check_student_submission.py --strict
```

两项检查均通过后，上传到 `main` 分支，并登记仓库链接和最终 commit ID。
