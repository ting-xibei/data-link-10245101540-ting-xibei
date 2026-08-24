# 10.2 实验成果提交

本实践按个人完成、个人提交。每名学生使用一个独立的私有 GitHub 仓库，仓库仅对本人、任课教师和助教开放。不得在多人共用仓库中按姓名建立个人文件夹。

## 一、接受并建立个人仓库

1. 使用本人 GitHub 账号登录 GitHub。
2. 打开教师提供的学生模板仓库或个人仓库链接。
3. 如果教师已经建立好个人仓库，接受邀请后直接进入该仓库；如果使用模板建立仓库，单击“Use this template”，选择“Create a new repository”。
4. 仓库所有者选择本人账号，仓库名称填写为 `data-link-学号-GitHub用户名`，可见性选择“Private”。
5. 创建完成后，将任课教师和三名助教加入仓库，权限为“Maintain”或“Write”。

## 二、下载实践仓库

在个人电脑上打开终端，执行以下命令。将示例地址替换为本人的仓库地址。

```powershell
git clone https://github.com/本人用户名/data-link-学号-GitHub用户名.git
cd data-link-学号-GitHub用户名
```

首次使用 Git 时，应先设置姓名和邮箱：

```powershell
git config --global user.name "本人姓名或GitHub用户名"
git config --global user.email "本人GitHub邮箱"
```

## 三、完成实验并保存成果

学生应在自己的仓库中完成 M1—M6。建议按以下结构保存：

```text
summer_school_practice_v1.0/
└─ student_package/
   ├─ src/                      完成后的M2—M6程序
   ├─ output/                   程序实际生成的结构化结果
   ├─ docs/                     流程图、核验说明和展示材料
   └─ SUBMISSION_README.md      综合运行说明
```

如果直接在课程提供的 `src_skeleton/` 中编写程序，可以保留该目录名，不必重复建立 `src/`。

`output/`至少应包括：

```text
encoded_messages.bin
decoded_partner_states.csv
validation_log.csv
roundtrip_report.csv
decoded_multitime.csv
track_table.csv
current_situation.csv
llm_mapping_candidate.csv
verified_mapping_table.csv
unified_situation.ndjson
alert_log.csv
quality_situation.csv
```

`docs/`至少应包括：

```text
M1_system_flow.pdf              系统处理流程图，也可使用PNG格式
M1_interface_risk.pdf           接口、通信与风险说明，也可使用DOCX或MD格式
M4_mapping_review.pdf           AI辅助映射核验说明，也可使用DOCX或MD格式
M6_presentation.pdf             不超过5页，也可使用PPTX格式
```

SQLite数据库、查询结果和航迹图为选做内容。不要上传 `.venv`、缓存、GitHub令牌、密码、个人隐私材料，也不要重复上传课程已经提供的大体积原始数据。

## 四、填写综合运行说明

将 `student_package/templates/m6_README_template.md` 复制为 `student_package/SUBMISSION_README.md`，填写姓名、学号、运行环境、运行命令、输入输出、实验结果、已知问题和映射来源。

README中的运行命令必须能够从空的 `output/` 目录重新生成结果。实验结果应写明处理记录数、目标数、生成帧数、成功解码帧数和发现的异常数量。

## 五、检查并上传

在仓库根目录依次执行：

```powershell
python summer_school_practice_v1.0/environment/run_smoke_test.py
python summer_school_practice_v1.0/environment/check_student_submission.py --strict
git status
git add summer_school_practice_v1.0/student_package
git commit -m "提交M1-M6个人实验成果"
git push origin main
```

检查程序出现“FAIL”时，应按提示补齐材料后再上传。

## 六、登记最终版本

上传完成后执行：

```powershell
git rev-parse HEAD
```

复制屏幕显示的完整 commit ID，并在课程指定的登记表中填写：

- 姓名和学号；
- GitHub用户名；
- 个人私有仓库链接；
- 最终commit ID。

截止时间以登记的commit ID在GitHub上的提交时间为准。截止后如需修改，应先征得教师或助教同意；未经同意的新提交不替代已经登记的版本。
