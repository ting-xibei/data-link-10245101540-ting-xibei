# M4 AI 辅助映射核验说明

- 候选来源：根据 `prompts/m4_llm_candidate_prompt_used.md` 在独立大模型会话中生成的 `reference/llm_generated_mapping_candidate.csv`；候选共 36 条，不作为最终规则。
- 使用材料：候选表、字段定义、TeachingLink 位宽/公式/标志位说明、`unified_model.json`，以及 M3 OpenSky 当前态势和 TeachingLink 样例。
- 候选核验：核心字段映射正确覆盖了速度、航向、垂直速度，且纬经度公式、高度 `code-1000`、有效位空值策略和 status bit2 的时间来源语义均正确。候选没有把协议整数 0 误写为物理 0。
- 发现的问题：候选将 `position_valid`、`time_valid` 和 `anomaly_flags` 标为 `UNRESOLVED`，并未给出航向越界、保留位或编码越界的处置；`source_format` 是映射上下文而非原始行字段；呼号还需在去补零后去除首尾空白。
- 人工修订依据与决策：坐标有效定义为纬经度均非 null 且范围合法；时间有效定义为正整数 Unix 秒，本实验不新增陈旧阈值；可选字段越界和未知来源写入 `anomaly_flags` 并把对应统一字段置为 `null`，但不改写上游 `message_valid`；只有保留位等帧结构异常可使 TeachingLink 的 `message_valid` 为 false。target_id 统一为六位小写十六进制，格式不合法则拒绝记录。
- 正式规则表：不再将 `source`、位置、质量和异常语义压缩为宽泛的 `quality.*` 行；按统一模型叶字段列出 OpenSky 17 条和 TeachingLink 17 条，异常标志在每种来源内合并为一条完整策略。
- 验证结果：形成 34 条已核验规则；转换 OpenSky 3 条、TeachingLink 3 条为 NDJSON。全部 6 条通过模型结构、标识、时间、位置有效性和高度类型自检；3 个同目标样例共享关键字段一致。`000001` 的垂直速度真实零值保留为 `0.0`；`780def` 缺失位置与呼号保留为 `null`。
- 局限性：验证仅覆盖课程提供的 3 条当前态势样例，不能证明对未见字段组合或实时来源的完备性；`message_valid` 仅代表结构/帧接收校验，不代表来源真实或飞行状态安全。
- 不由 AI 决定：位宽、比例因子、偏置、单位、有效位空值策略、状态来源语义和最终 `verified` 结论均以协议与字段定义为准。
