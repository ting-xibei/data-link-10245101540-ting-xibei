# M4 两种来源字段和来源语义说明

本文件与 `teaching_message_spec.md`、`opensky_field_dictionary.csv`、`partner_field_dictionary.csv`、`unified_model.json` 一起构成 M4 人工核验的权威依据。

## OpenSky 当前态势来源

| 统一字段|OpenSky来源|教学消息来源|规则|
| ---------------------- | ------------------ | --------------------------------------- | -------------------------------------------------------- |
| track_id               | target_id          | target_id                               | 统一转为六位小写十六进制字符串，保留前导0                |
| timestamp              | latest_time        | timestamp                               | 直接映射，必须为正整数                                   |
| quality.time_source    | timestamp_source   | status_flags.bit2                       | position_time或last_contact_fallback                     |
| identity.callsign      | callsign           | callsign＋validity_flags.bit6           | 无效时为null；有效时去除补0                              |
| position.lat           | lat                | latitude_code＋validity_flags.bit0      | 无效时null；有效时code/(2²²−1)×180−90                    |
| position.lon           | lon                | longitude_code＋validity_flags.bit1     | 无效时null；有效时code/(2²²−1)×360−180                   |
| position.alt           | altitude           | altitude_code＋validity_flags.bit2      | 无效时null；有效时code−1000，单位米                      |
| position.alt_type      | baro／geo来源      | status_flags.bit1                       | altitude有效时0=barometric、1=geometric；无效时unknown   |
| motion.speed           | speed              | speed_code＋validity_flags.bit3         | 无效时null；有效时code×0.1 m/s                           |
| motion.heading         | heading            | heading_code＋validity_flags.bit4       | 无效时null；有效时code×0.01°且小于360°                   |
| motion.vertical_rate   | vertical_rate      | vertical_rate_code＋validity_flags.bit5 | 无效时null；有效时code×0.01−327.68 m/s                   |
| status.on_ground       | on_ground          | status_flags.bit0                       | 转换为布尔值                                             |
| quality.position_valid | lat／lon非空且合法 | 纬经有效位＋解码范围                    | 纬度和经度均有效且解码值处于合法范围                     |
| quality.time_valid     | latest_time有效    | timestamp及帧接收结果                   | timestamp为正整数；时间回退不等于时间无效                |
| quality.message_valid  | 源记录结构校验结果 | 完整帧接收判据                          | 头字段、长度、校验和、保留位、标志一致性及必需字段均通过 |

## 人工核验要求

候选映射只用于辅助。每条正式映射必须填写单位转换、空值策略、证据和 `verified`；至少用一个真实零值样例和一个字段缺失样例验证。
