# 数据链软件暑期学校学生实践包

本包包含 M1-M6 实验所需的离线数据、Schema、模板、提示和代码骨架。

## 开始前

先按 `../environment/README_environment.md` 在正式课程包根目录建立独立 `.venv`，再运行：

```powershell
.\.venv\Scripts\python.exe environment\run_student_checks.py
```

确认全部学生检查通过后再开始实践。环境安装、验证命令和不可用时的降级路径统一以环境说明为准。

## M1 体系理解

- 输入：`data/raw_states.json`、`guides/opensky_interface_summary.md`、`guides/m1_guided_questions.md`、`schema/teaching_message_spec.md`、字段字典。
- 模板：`templates/m1_system_template.md`。
- 输出：系统处理流程图、接口/通信/风险说明。

## M2 协议解析与消息编解码

- 输入：`raw_states.json`、两个字段字典、41 字节 TeachingLink 规范。
- 骨架：`src_skeleton/m2_protocol.py`。
- 输出：Parser/Codec、`encoded_messages.bin`、`decoded_partner_states.csv`、`validation_log.csv`、`roundtrip_report.csv`。
- 重点：大端字节序、22 位经纬度、统一量化、状态/有效性标志、保留位、教学校验和、真实零值与缺失值区分。

## M3 单源多时刻关联与当前态势

- 输入：`data/partner_messages_multitime.bin`（9 帧、369 字节）。
- 骨架：`src_skeleton/m3_tracks.py`。
- 输出：`decoded_multitime.csv`、`track_table.csv`、`current_situation.csv`；SQLite/航迹图选做。
- 输入帧边界已对齐；要求处理不完整尾帧，不要求失步重同步。

### OpenSky 真实数据

`data/opensky_real/` 是从 OpenSky 官方匿名 REST API 实际下载的 3 个快照，共 71 条状态向量，不是人工编造数据。该目录用于学生使用本人完成的 M2-M3 代码进行真实数据兼容性验证，不包含助教逐记录往返参考结果。

## M4 语义互操作

- 输入：`data/m4/partner_current_situation.csv`、字段定义、`unified_model.json`。
- 候选：自行使用大模型，或使用 `reference/pre_generated_mapping_candidate.csv`。
- 骨架：`src_skeleton/m4_mapping.py`。
- 输出：候选映射、人工核验映射、`unified_situation.ndjson`、一页核验说明。
- 候选中故意保留可识别问题，不能直接当答案。

## M5 一致性保障

- 输入：`data/m5/anomaly_cases.csv`、`data/m5/anomaly_rules.csv`。
- 骨架：`src_skeleton/m5_quality.py`。
- 输出：`alert_log.csv`、`quality_situation.csv`、异常结果说明。
- 必做规则：位置缺失、延迟、联合键重复、航向越界。

## M6 综合演练

将 M2-M5 代码接入 `src_skeleton/run_all.py`，从空 `output/` 目录执行。README 使用 `templates/m6_README_template.md`，并记录输入、输出和实验结果；运行命令见该模板。

前序结果阻断后续模块时，只有在助教A正式发布后才可按 `templates/checkpoint_switch.md` 使用官方检查点；检查点不能替代本人前序成果。

完整提交项见 `templates/submission_checklist.md`。

## 个人提交

本实践按个人完成、个人提交。每名学生使用一个独立的私有 GitHub 仓库，不要在多人共用仓库中按姓名建立文件夹。

提交前完成以下操作：

1. 将完成后的程序放在 `src/`；如果一直在 `src_skeleton/` 中编写，也可以保留原目录名。
2. 将程序实际生成的必交结果保存在 `output/`，不要只放截图。
3. 将流程图、说明和展示材料保存在 `docs/`。
4. 根据 `templates/m6_README_template.md` 完成根目录下的 `SUBMISSION_README.md`。
5. 在课程包根目录执行 `.\.venv\Scripts\python.exe environment\check_student_submission.py --strict`，修正所有失败项。
6. 将最终文件提交并上传到个人仓库的 `main` 分支，在课程指定渠道登记仓库链接和最终 commit ID。

具体操作和文件命名见 `guides/student_submission_guide.md`。
