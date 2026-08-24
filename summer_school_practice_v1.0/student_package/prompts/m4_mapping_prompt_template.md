# M4 候选映射提示模板

你只生成候选映射，不生成最终代码，也不替代人工核验。

输入材料：

1. OpenSky 与 TeachingLink 字段定义；
2. TeachingLink 位宽、比例因子、偏置、状态位和有效性位；
3. 学校给定的统一模型；
4. 输出列：`source_format,input_field,candidate_unified_field,candidate_rule,confidence,review_note`。

要求：

- 每行只描述一个候选映射；
- 明确单位转换和空值策略；
- 无法确定时降低 confidence 并说明缺少的证据；
- 不把协议整数 0 自动解释为真实物理值 0；
- 不把 `message_valid` 解释为来源可信或安全完整性；
- 输出 CSV，不添加最终结论。
