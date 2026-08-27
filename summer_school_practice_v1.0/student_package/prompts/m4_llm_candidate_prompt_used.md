# M4 实际使用的候选映射提示词

你只负责生成 M4 的候选映射表，不生成最终代码，不作最终结论，也不替代人工核验。

任务是把 OpenSky 和 TeachingLink 两类航空态势来源映射到统一态势模型。候选仅供人工审核：无法根据材料确定时必须写 `UNRESOLVED`，不得猜测或声称已经验证。

提供材料包括：

- OpenSky 的标识、时间、位置、运动、状态、时间来源与 `message_valid` 字段定义；
- TeachingLink 的 6 位目标标识、定长呼号、时间、六个协议整数、`validity_flags`、`status_flags` 和 `message_valid` 字段定义；
- TeachingLink 的数值恢复公式：纬度 `code/(2^22-1)*180-90`、经度 `code/(2^22-1)*360-180`、高度 `code-1000`、速度 `code*0.1`、航向 `code*0.01`、垂直速度 `code*0.01-327.68`；
- 有效位 bit0--bit6 分别控制纬度、经度、高度、速度、航向、垂直速度和呼号；状态位 bit0、bit1、bit2 分别表示地面状态、高度类型和时间来源；
- 统一模型的字段：`source`、`track_id`、`timestamp`、`identity.callsign`、`position.*`、`motion.*`、`status.on_ground`、`quality.*`。

只输出 CSV，第一行必须为：

`source_format,input_field,candidate_unified_field,candidate_rule,confidence,review_note`

每行只描述一个字段或明确字段组合。尽量覆盖统一模型全部必需字段；明确单位、比例因子、偏置和空值策略。不要将协议整数 0 自动解释为物理值 0；不要将 `message_valid` 扩大解释为来源真实、可信或飞行安全。不得把候选写成最终结论。
