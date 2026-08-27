# M6 综合运行说明

## 基本信息

- 姓名：赵熙焙
- 学号：10245101540
- GitHub用户名：ting-xibei
- Python版本：3.14.7
- 是否使用SQLite：是
- M4候选来源：依据已保存提示词生成的AI候选

## 安装与运行

先按课程包 `environment/README_environment.md` 建立独立 `.venv`。在课程包根目录执行：

```powershell
.\.venv\Scripts\python.exe student_package\src_skeleton\run_all.py
```

入口会清理 `student_package/output/` 中已有生成物（保留说明性 `README.md`），再从固定输入重新生成全部成果。

## 程序入口

`run_all.py` 的调用顺序为：M2 解析/编码/接收校验 → 41 字节帧对齐核验 → M3 SQLite 持久化、航迹和当前态势 → M3 OpenSky 真实数据验证 → M4 人工核验映射 → M5 一致性检查 → 关键成果重新读取与导出。

## 输入文件

- `data/raw_states.json`：M2 OpenSky 状态向量；
- `data/partner_messages_multitime.bin`：M3 9 帧多时刻 TeachingLink 消息；
- `data/opensky_real/source/`：M3 真实OpenSky冻结快照；
- `data/m4/partner_current_situation.csv`、字段定义和统一模型：M4；
- `data/m5/anomaly_cases.csv`、`data/m5/anomaly_rules.csv`：M5。

## 输出文件

M2：`encoded_messages.bin`、`decoded_partner_states.csv`、`validation_log.csv`、`roundtrip_report.csv`。

M3：`decoded_multitime.csv`、`track_table.csv`、`current_situation.csv`、`states.db`、`sqlite_query_result.csv`、`m3_trajectory.png`。

M3真实数据验证：`receiver_situation_initial.csv`、`selected_source_states.csv`、`transmitted_frames.bin`、`transmission_log.csv`、`decoded_states.csv`、`receiver_situation_final.csv`、`received_states.db`、`precision_error_report.csv`、`experiment_summary.json`。

M4：`llm_mapping_candidate.csv`、`verified_mapping_table.csv`、`unified_situation.ndjson`；核验说明保存为 `docs/M4_mapping_review.md`。

M5：`alert_log.csv`、`quality_situation.csv`。

## 实验结果

- M2：编码 4 帧、解码 4 条、校验日志 14 条、量化往返检查 28 项；
- M3：输入 369 字节，解码 9 条，形成 9 个航迹点、3 个当前目标，SQLite 重读 9 条；
- M3真实数据验证：读取 3 个OpenSky快照、71 条状态，编码并成功解码 71 帧，形成 24 个当前目标，497/497 项精度检查通过；
- M4：保留 36 条候选，形成 34 条已核验映射，输出 6 条统一消息；
- M5：检查 6 条样例，输出 5 条告警和 6 条质量态势。

## 已知限制

- TeachingLink 为课程自定义教学协议，`message_valid` 只代表帧结构与接收校验，不代表数据真实性或飞行安全；
- OpenSky真实数据验证使用课程包中冻结的3个快照，不代表实时航空态势；
- M5 选做帧异常规则已实现，但固定 M5 样例均为有效帧，真实无效帧仅通过程序内构造测试覆盖；
- M4 的跨源验证基于课程提供的当前态势样例；最终 commit ID 需在提交前由本人填写。

## 最终提交信息

- 仓库链接：https://github.com/ting-xibei/data-link-10245101540-ting-xibei
- 最终commit ID：未提供（提交前填写）
- 最后检查日期：2026-08-27
