# TeachingLink 位置状态教学帧规范

> TeachingLink 是学校自定义教学协议，不对应 ASTERIX、ADS-B/Mode-S、Link 16、企业装备协议或任何行业标准。`message_valid` 仅代表帧通过本规范的格式与校验检查。

## 固定约定

- 网络字节序（大端）
- 每帧固定 41 字节，一帧承载一条位置状态消息
- 数值字段使用无符号整数、比例因子和偏置，不使用 IEEE 浮点数
- 统一量化函数：`Q(y) = floor(y + 0.5)`，禁止依赖语言默认 `round`
- 可空字段由 `validity_flags` 表达；无效时占位字节必须全为 0

## 字段布局

| 字段 | 类型/长度 | 偏移 | 规则 |
|---|---:|---:|---|
| magic | uint16/2 | 0-1 | 固定 `0x4453` |
| version | uint8/1 | 2 | 固定 `1` |
| message_type | uint8/1 | 3 | 固定 `1` |
| message_length | uint16/2 | 4-5 | 固定 `41` |
| message_seq | uint16/2 | 6-7 | 达到 65535 后按模 65536 回绕 |
| timestamp | uint32/4 | 8-11 | 优先位置时间，必要时回退最近联系时间 |
| target_id | uint24/3 | 12-14 | 六位 icao24，保留前导 0，必需 |
| callsign | ASCII/8 | 15-22 | 有效时 1-8 字节，不足补 0，不静默截断 |
| latitude_code | 22 位有效/3 | 23-25 | 最高 2 位保留为 0 |
| longitude_code | 22 位有效/3 | 26-28 | 最高 2 位保留为 0 |
| altitude_code | uint16/2 | 29-30 | 1 m 分辨率，物理偏置 1000 m |
| speed_code | uint16/2 | 31-32 | 0.1 m/s 分辨率 |
| heading_code | uint16/2 | 33-34 | 0.01° 分辨率，`0 <= heading < 360` |
| vertical_rate_code | uint16/2 | 35-36 | 0.01 m/s，物理偏置 327.68 m/s |
| status_flags | uint8/1 | 37 | 状态与来源 |
| validity_flags | uint8/1 | 38 | 可空字段有效性 |
| checksum | uint16/2 | 39-40 | 前 39 字节之和模 65536 |

## 标志位

`status_flags`：bit0=`on_ground`，bit1=`altitude_is_geometric`，bit2=`timestamp_fallback`，bit3-bit7 保留为 0。

`validity_flags`：bit0=纬度、bit1=经度、bit2=高度、bit3=速度、bit4=航向、bit5=垂直速度、bit6=呼号；bit7 保留为 0。

有效位为 1 且协议整数为 0，表示该编码对应的真实物理量；有效位为 0 且占位整数为 0，表示字段缺失。不得仅凭整数是否为 0 判断空值。

## 定点编码

- 纬度：`Q((lat + 90) / 180 * (2^22 - 1))`
- 经度：`Q((lon + 180) / 360 * (2^22 - 1))`
- 高度：`Q(altitude_m + 1000)`
- 地速：`Q(speed_m_s / 0.1)`
- 航向：`Q(heading_deg / 0.01)`
- 垂直速度：`Q((vertical_rate_m_s + 327.68) / 0.01)`

编码前必须检查量程，禁止用截断、掩码或取模静默处理越界值。有效字段往返误差原则上不超过一个量化单位。

## 接收判据

接收端依次检查长度、magic、version、message_type、checksum、经纬度容器保留位、两个标志字节保留位、标志/占位一致性，以及 `target_id`、`timestamp` 等必需字段。可选字段缺失不自动使整帧无效；非法帧应记录错误，不能导致程序整体崩溃。
