# M5 异常结果说明

- 批次时间：`1710000120`。
- 四类必做规则是否均运行：是。R1 位置缺失、R2 数据延迟、R3 `target_id+timestamp` 联合键重复、R4 航向越界均已执行。
- 告警总数及按类型统计：共 5 条；`POSITION_MISSING` 1 条、`DATA_DELAYED` 1 条、`DUPLICATE_RECORD` 2 条、`HEADING_OUT_OF_RANGE` 1 条。
- HIGH/MEDIUM 数量：HIGH 1 条（`780def` 的纬度缺失）；MEDIUM 4 条（`000001` 延迟、`780aaa` 两条重复、`780bbb` 航向为 360）。
- 正常记录是否被误报：否。`780abc` 没有告警，质量态势为 `NONE/NORMAL`。
- `heading=360` 与 `heading` 为空的处理：360 不属于 `[0, 360)`，触发 R4；空航向不触发 R4。
- 字段缺失、字段级诊断、帧验证失败和来源真实性彼此独立：位置字段缺失触发 R1，但不等于帧无效；通用 `validation_errors` 可以包含可选字段越界等诊断，不能据此打回整帧。仅 `message_valid=false` 或上游明确携带 `frame_validation_errors` 时，选做规则才生成 `FRAME_VALIDATION_ERROR`；`message_valid` 只表示 TeachingLink 帧结构和接收校验，不证明来源真实或飞行状态安全。
- 样例限制：固定样例的 `message_valid` 均为真，因此实际 5 条告警均来自必做规则；选做帧异常已通过构造无效帧和上游校验错误样例验证。
