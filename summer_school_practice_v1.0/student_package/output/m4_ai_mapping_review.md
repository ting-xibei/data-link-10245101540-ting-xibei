# M4 AI 辅助映射核验说明

- 候选来源：学校提供的 `reference/pre_generated_mapping_candidate.csv`（作为 AI/自动候选，不作为最终规则）。
- 使用材料：候选表、`source_field_definitions.md`、`teaching_message_spec.md`、两个字段字典、`unified_model.json`，以及 M3 OpenSky 当前态势和 TeachingLink 样例。
- 发现的问题：候选将 TeachingLink 纬度/经度目标字段对调；高度规则遗漏 `-1000 m` 偏置；呼号未结合有效位；`status_flags.bit2` 被错误写为 `quality.time_valid`，没有表达其时间回退来源语义；并且未覆盖全部必需字段。
- 修订依据：规范规定纬度、经度均为 22 位但公式量程不同；高度为 `code-1000`；validity bit6 控制呼号；status bit2 是 `timestamp_fallback`。正式映射从编码列和标志位恢复物理量，有效位为 0 时写入 `null`。
- 优化与修订过程：先原样保留 8 条候选，逐行与字段定义比对；随后将经纬度映射分别改为 `latitude_code→position.lat`、`longitude_code→position.lon`，并应用各自公式。再把高度规则由“code乘1米”修正为 `code-1000`，把呼号规则补充为“validity bit6 为 0 时 null”，把 status bit2 从 `time_valid` 改为 `quality.time_source`（0=position_time，1=last_contact_fallback）。最后补齐候选未覆盖的速度、航向、垂直速度、地面状态、质量字段及空值策略，形成 25 条正式规则；实现时只从 TeachingLink 的编码列和标志位恢复数值，不借用其已换算展示列。
- 验证结果：读取 8 条候选并形成 25 条已核验规则；转换 OpenSky 3 条、TeachingLink 3 条为 NDJSON。全部 6 条通过模型结构、标识、时间、位置有效性和高度类型自检；3 个同目标样例共享关键字段一致。目标 `000001` 的垂直速度真实零值保留为 `0.0`；`780def` 缺失位置与呼号保留为 `null`。
- 局限性：验证仅覆盖课程提供的 3 条当前态势样例，不能证明对未见字段组合或实时来源的完备性；`message_valid` 仅代表结构/帧接收校验，不代表来源真实或飞行状态安全。
- 不由 AI 决定：位宽、比例因子、偏置、单位、有效位空值策略、状态来源语义和最终 `verified` 结论均以协议与字段定义为准。
