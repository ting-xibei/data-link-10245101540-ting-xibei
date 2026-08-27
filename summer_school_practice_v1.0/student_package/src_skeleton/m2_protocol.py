"""M2：把 OpenSky 状态数组编码为 TeachingLink 帧，并在接收端恢复与校验。

本模块模拟一条完整的数据链处理链路：

OpenSky 数组 → 发送方内部记录 → 41 字节 TeachingLink 帧
→ 接收端帧校验 → 结构化状态 → 往返量化误差报告。

程序最终生成四项手册规定的成果：

* encoded_messages.bin：连续存放通过发送端检查的 41 字节帧；
* decoded_partner_states.csv：接收端恢复的物理值、协议整数和有效性；
* validation_log.csv：源记录错误以及人工构造的坏帧验证结果；
* roundtrip_report.csv：源值与解码值的误差和容差比较。

TeachingLink 是课程自定义教学协议。这里的 ``message_valid`` 只表示帧通过
本实验规定的格式与校验检查，不表示目标身份、位置或飞行状态在现实中可信。
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Callable


# TeachingLink 固定帧的基础约定，编码端和解码端必须共用同一组值。
# 如果只修改其中一端，发送方生成的帧将无法被接收方按相同口径解释。
FRAME_SIZE = 41
MAGIC = 0x4453
VERSION = 1
MESSAGE_TYPE = 1
# 经纬度装在 3 字节容器中，但课程只允许低 22 位有效，最高 2 位必须保持为 0。
MAX_22BIT = (1 << 22) - 1
# 航向分辨率为 0.01 度且合法范围是 [0, 360)，因此最大合法协议码为 35999。
# 单独定义上限，供发送端量化后检查和接收端协议码检查共同使用。
MAX_HEADING_CODE = 35999

# validity_flags 的 bit0-bit6 分别表示七个可空字段是否存在。
# 协议整数等于 0 并不代表字段缺失；必须结合这里对应的有效位判断。
VALIDITY_BITS = {
    "lat": 0,
    "lon": 1,
    "altitude": 2,
    "speed": 3,
    "heading": 4,
    "vertical_rate": 5,
    "callsign": 6,
}


class ProtocolError(ValueError):
    """携带课程规定错误类型的可记录异常。

    普通 ``ValueError`` 只有文字消息，不足以直接生成 validation_log.csv。
    本异常额外保存字段、统一问题类型、原值和说明，使上层捕获异常后可以
    原样写成一条结构稳定的验证日志，而不必解析异常文本。
    """

    def __init__(self, field: str, problem_type: str, value: Any, description: str) -> None:
        super().__init__(description)
        self.field = field
        self.problem_type = problem_type
        self.value = value
        self.description = description


def _problem(field: str, problem_type: str, value: Any, description: str) -> ProtocolError:
    """创建统一格式的字段错误，供解析、编码和上层日志共用。"""
    return ProtocolError(field, problem_type, value, description)


def _is_integer(value: Any) -> bool:
    """严格判断整数，同时排除 Python 中属于 ``int`` 子类的布尔值。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(field: str, value: Any) -> float:
    """把必需数值转成有限浮点数，拒绝布尔值、NaN 和正负无穷。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _problem(field, "TYPE_ERROR", value, "字段必须是有限数值。")
    number = float(value)
    if not math.isfinite(number):
        raise _problem(field, "TYPE_ERROR", value, "字段必须是有限数值。")
    return number


def _nullable_number(field: str, value: Any, low: float, high: float) -> float | None:
    """校验可空物理量；``None`` 保持为空，非空值必须落在闭区间内。"""
    if value is None:
        return None
    number = _finite_number(field, value)
    if not low <= number <= high:
        raise _problem(field, "OUT_OF_RANGE", value, f"字段量程必须在 [{low}, {high}] 内。")
    return number


def _optional_or_missing(
    errors: list[ProtocolError],
    validator: Callable[..., Any],
    *args: Any,
) -> Any:
    """把可选字段错误降级为缺失，同时保留可审计的原始错误。

    TeachingLink 用有效位表达可选字段是否可用。因而可选字段类型错误、编码
    错误或量程越界时，可以记录错误并将该字段按缺失封装；这不应自动抛弃
    target_id、timestamp 和 on_ground 仍然有效的整条记录。
    """
    try:
        return validator(*args)
    except ProtocolError as error:
        errors.append(error)
        return None


def _target_id(value: Any) -> str:
    """规范化六位 icao24，同时保留 ``000001`` 这类有意义的前导零。"""
    if not isinstance(value, str):
        raise _problem("target_id", "TYPE_ERROR", value, "target_id 必须是六位十六进制字符串。")
    target = value.lower()
    if len(target) != 6 or any(char not in "0123456789abcdef" for char in target):
        raise _problem("target_id", "OUT_OF_RANGE", value, "target_id 必须恰好为六位十六进制字符串。")
    return target


def _callsign(value: Any) -> str | None:
    """清理可空呼号，并保证其能无损装入协议规定的 8 字节 ASCII 区域。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _problem("callsign", "TYPE_ERROR", value, "callsign 必须是字符串或空值。")
    callsign = value.strip()
    if not callsign:
        raise _problem("callsign", "ENCODING_ERROR", value, "非空 callsign 去除空格后必须有 1 到 8 个 ASCII 字符。")
    try:
        raw = callsign.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _problem("callsign", "ENCODING_ERROR", value, "callsign 只能包含 ASCII 字符。") from exc
    if not 1 <= len(raw) <= 8:
        raise _problem("callsign", "ENCODING_ERROR", value, "callsign 必须为 1 到 8 个 ASCII 字符。")
    return callsign


def _timestamp(value: Any) -> int:
    """校验时间戳能够无损写入协议的四字节无符号整数字段。"""
    if not _is_integer(value) or not 0 <= value <= 0xFFFFFFFF:
        raise _problem("timestamp", "OUT_OF_RANGE", value, "timestamp 必须是 uint32 范围内的整数。")
    return value


def _quantize(value: float) -> int:
    """执行课程规定的 ``Q(y)=floor(y+0.5)``。

    不能换成 Python ``round``：Python 在恰好位于 .5 时采用偶数舍入，
    可能使不同语言实现得到不同协议整数。
    """
    return math.floor(value + 0.5)


def _heading(value: Any) -> float | None:
    """校验航向既满足物理范围，也能量化成 0..35999。"""
    heading = _nullable_number("heading", value, 0.0, math.nextafter(360.0, -math.inf))
    if heading is not None and _quantize(heading / 0.01) > MAX_HEADING_CODE:
        raise _problem(
            "heading",
            "OUT_OF_RANGE",
            value,
            "heading 按 0.01 度量化后必须得到 0 到 35999 的协议整数。",
        )
    return heading


def parse_state_vector(vector: list[Any]) -> dict[str, Any]:
    """将 OpenSky 状态向量转换为发送方内部结构化记录。

    OpenSky 使用固定下标数组传递状态，便于网络接口压缩数据，却不利于后续
    代码理解和检查。本函数按照字段字典取值、处理课程规定的回退关系，并输出
    带字段名的字典。这里只完成“源数据语义 → 发送端语义”，尚未进行二进制编码。
    """
    # M2 使用到的最高下标是 13；长度不足时不能继续按下标访问。
    if not isinstance(vector, list) or len(vector) <= 13:
        raise _problem("state_vector", "LENGTH_ERROR", vector, "状态向量长度不足，无法读取 M2 所需字段。")

    # target_id 对应 OpenSky 的 icao24。先按字符串保存，编码时再转为 uint24，
    # 这样能够在 CSV 和内部记录中保留六位表示以及前导零。
    target = _target_id(vector[0])

    # 时间优先级来自手册：位置更新时间优先；为空时回退到最近联系时间。
    # timestamp_source 会在编码时写入 status_flags.bit2，使接收端知道来源。
    position_time, last_contact = vector[3], vector[4]
    if position_time is not None:
        timestamp = _timestamp(position_time)
        timestamp_source = "position_time"
    elif last_contact is not None:
        timestamp = _timestamp(last_contact)
        timestamp_source = "last_contact_fallback"
    else:
        raise _problem("timestamp", "REQUIRED_FIELD_MISSING", None, "time_position 与 last_contact 均为空。")

    # on_ground 是必需字段，且 bool 与数值 0/1 在语义上不能混用。
    on_ground = vector[8]
    if not isinstance(on_ground, bool):
        raise _problem("on_ground", "TYPE_ERROR", on_ground, "on_ground 必须是布尔值。")

    # 可选字段错误只影响相应有效位；先集中保存，以便 run_m2 写验证日志。
    field_errors: list[ProtocolError] = []

    # 高度同样有明确优先级：气压高度优先，缺失时才使用几何高度。
    # alt_type 最终通过 status_flags.bit1 穿过协议链路。
    baro_altitude, geo_altitude = vector[7], vector[13]
    if baro_altitude is not None:
        altitude = _optional_or_missing(field_errors, _nullable_number, "altitude", baro_altitude, -1000.0, 64535.0)
        alt_type = "barometric" if altitude is not None else "unknown"
    elif geo_altitude is not None:
        altitude = _optional_or_missing(field_errors, _nullable_number, "altitude", geo_altitude, -1000.0, 64535.0)
        alt_type = "geometric" if altitude is not None else "unknown"
    else:
        altitude = None
        alt_type = "unknown"

    # 其余运动字段都是可空字段：None 表示源数据确实缺失，真实数值 0 必须保留。
    # 每个非空值在此处先做物理量程检查，避免编码时靠截断或取模掩盖错误。
    return {
        "target_id": target,
        "callsign": _optional_or_missing(field_errors, _callsign, vector[1]),
        "timestamp": timestamp,
        "timestamp_source": timestamp_source,
        "lat": _optional_or_missing(field_errors, _nullable_number, "lat", vector[6], -90.0, 90.0),
        "lon": _optional_or_missing(field_errors, _nullable_number, "lon", vector[5], -180.0, 180.0),
        "altitude": altitude,
        "alt_type": alt_type,
        "speed": _optional_or_missing(field_errors, _nullable_number, "speed", vector[9], 0.0, 6553.5),
        "heading": _optional_or_missing(field_errors, _heading, vector[10]),
        "vertical_rate": _optional_or_missing(field_errors, _nullable_number, "vertical_rate", vector[11], -327.68, 327.67),
        "on_ground": on_ground,
        "_field_errors": field_errors,
    }


def calculate_checksum(data_without_checksum: bytes) -> int:
    """计算前 39 字节无符号字节值之和模 65536。

    这是课程规定的轻量帧校验，不是密码学哈希。发送端把结果写入最后两字节，
    接收端对收到的前 39 字节重新计算并比较，用于发现实验中的帧损坏。
    """
    return sum(data_without_checksum) % 65536


def _encode_optional(frame: bytearray, offset: int, width: int, code: int | None, bit: int, validity: int) -> int:
    """写入一个可选协议整数，并同步更新其有效位。

    ``bytearray`` 初始值全为 0，因此字段缺失时不写数据即可得到全零占位区，
    同时保持有效位为 0。字段存在时写入大端整数并置位。返回新标志值是因为
    整数不可变，调用方需要接住更新后的 validity_flags。
    """
    if code is None:
        return validity
    if not 0 <= code < (1 << (width * 8)):
        raise _problem("protocol_code", "ENCODING_ERROR", code, "协议整数超出字段位宽。")
    frame[offset : offset + width] = code.to_bytes(width, "big")
    return validity | (1 << bit)


def encode_position_message(
    record: dict[str, Any],
    message_seq: int,
    field_errors: list[ProtocolError] | None = None,
) -> bytes:
    """按固定偏移把一条发送方记录封装为 41 字节 TeachingLink 帧。

    编码顺序是：再次校验公开接口输入 → 写固定帧头和必需字段 → 量化可选
    物理量 → 写有效位和来源状态位 → 计算校验和。再次校验是为了保证即使
    调用方没有经过 ``parse_state_vector``，本函数也不会静默写出明显越界数据。
    """
    if not isinstance(record, dict):
        raise _problem("record", "TYPE_ERROR", record, "发送记录必须是字典。")
    if not _is_integer(message_seq) or message_seq < 0:
        raise _problem("message_seq", "TYPE_ERROR", message_seq, "message_seq 必须是非负整数。")

    # 必需字段没有有效位可供接收端表示“缺失”，因此编码前必须全部可用。
    target = _target_id(record.get("target_id"))
    timestamp = _timestamp(record.get("timestamp"))
    on_ground = record.get("on_ground")
    if not isinstance(on_ground, bool):
        raise _problem("on_ground", "TYPE_ERROR", on_ground, "on_ground 必须是布尔值。")

    # 可选字段错误被记录并降级为缺失；必需字段错误仍由上面的校验直接拒绝。
    # 合法真实零值不会被降级，只有 None 或校验失败才清除对应有效位。
    diagnostics = field_errors if field_errors is not None else []
    callsign = _optional_or_missing(diagnostics, _callsign, record.get("callsign"))
    lat = _optional_or_missing(diagnostics, _nullable_number, "lat", record.get("lat"), -90.0, 90.0)
    lon = _optional_or_missing(diagnostics, _nullable_number, "lon", record.get("lon"), -180.0, 180.0)
    altitude = _optional_or_missing(diagnostics, _nullable_number, "altitude", record.get("altitude"), -1000.0, 64535.0)
    speed = _optional_or_missing(diagnostics, _nullable_number, "speed", record.get("speed"), 0.0, 6553.5)
    heading = _optional_or_missing(diagnostics, _heading, record.get("heading"))
    vertical_rate = _optional_or_missing(diagnostics, _nullable_number, "vertical_rate", record.get("vertical_rate"), -327.68, 327.67)

    # bytearray 默认填 0，恰好符合可空字段缺失时占位字节必须全零的要求。
    # 所有多字节整数均使用网络字节序（大端）。
    frame = bytearray(FRAME_SIZE)
    frame[0:2] = MAGIC.to_bytes(2, "big")
    frame[2] = VERSION
    frame[3] = MESSAGE_TYPE
    frame[4:6] = FRAME_SIZE.to_bytes(2, "big")
    frame[6:8] = (message_seq % 65536).to_bytes(2, "big")
    frame[8:12] = timestamp.to_bytes(4, "big")
    frame[12:15] = int(target, 16).to_bytes(3, "big")

    # 呼号是定长 8 字节 ASCII。有效呼号不足 8 字节时在尾部补 0；
    # 不允许静默截断，因为截断会改变目标标识语义。
    validity = 0
    if callsign is not None:
        raw_callsign = callsign.encode("ascii")
        frame[15:23] = raw_callsign.ljust(8, b"\x00")
        validity |= 1 << VALIDITY_BITS["callsign"]

    # 将物理量转换成协议整数。经纬度映射到 22 位；其余字段使用分辨率和偏置。
    # None 不参与计算，随后由 _encode_optional 留下全零占位区。
    latitude_code = None if lat is None else _quantize((lat + 90.0) / 180.0 * MAX_22BIT)
    longitude_code = None if lon is None else _quantize((lon + 180.0) / 360.0 * MAX_22BIT)
    altitude_code = None if altitude is None else _quantize(altitude + 1000.0)
    speed_code = None if speed is None else _quantize(speed / 0.1)
    heading_code = None if heading is None else _quantize(heading / 0.01)
    vertical_rate_code = None if vertical_rate is None else _quantize((vertical_rate + 327.68) / 0.01)

    # 严格按照协议表中的固定偏移写入，不能根据字段是否为空改变后续字段位置。
    validity = _encode_optional(frame, 23, 3, latitude_code, VALIDITY_BITS["lat"], validity)
    validity = _encode_optional(frame, 26, 3, longitude_code, VALIDITY_BITS["lon"], validity)
    validity = _encode_optional(frame, 29, 2, altitude_code, VALIDITY_BITS["altitude"], validity)
    validity = _encode_optional(frame, 31, 2, speed_code, VALIDITY_BITS["speed"], validity)
    validity = _encode_optional(frame, 33, 2, heading_code, VALIDITY_BITS["heading"], validity)
    validity = _encode_optional(frame, 35, 2, vertical_rate_code, VALIDITY_BITS["vertical_rate"], validity)

    # status_flags 记录状态和“值从哪里来”：bit0 在地面，bit1 几何高度，
    # bit2 时间回退。其余位保持 bytearray 的初始零值，作为协议保留位。
    status = int(on_ground)
    if altitude is not None and record.get("alt_type") == "geometric":
        status |= 1 << 1
    if record.get("timestamp_source") == "last_contact_fallback":
        status |= 1 << 2
    frame[37] = status
    frame[38] = validity
    # 校验和只覆盖偏移 0-38；偏移 39-40 是校验和自身，不能参与计算。
    frame[39:41] = calculate_checksum(bytes(frame[:39])).to_bytes(2, "big")
    return bytes(frame)


def _empty_decoded(errors: list[tuple[str, str, str]]) -> dict[str, Any]:
    """为连固定字段都无法安全读取的帧构造统一失败结果。

    例如长度不是 41 时，继续访问固定偏移可能得到误导性数据甚至越界。因此
    接收端返回与正常结果相同的列结构，但物理值和协议码置空、有效性置 False，
    让批处理程序能够记录错误后继续处理下一帧。
    """
    return {
        "target_id": None,
        "callsign": None,
        "timestamp": None,
        "timestamp_source": None,
        "time_source": None,
        "message_seq": None,
        "lat": None,
        "lon": None,
        "altitude": None,
        "alt_type": "unknown",
        "speed": None,
        "heading": None,
        "vertical_rate": None,
        "on_ground": None,
        "status_flags": None,
        "validity_flags": None,
        "latitude_code": None,
        "longitude_code": None,
        "altitude_code": None,
        "speed_code": None,
        "heading_code": None,
        "vertical_rate_code": None,
        "lat_valid": False,
        "lon_valid": False,
        "altitude_valid": False,
        "speed_valid": False,
        "heading_valid": False,
        "vertical_rate_valid": False,
        "callsign_valid": False,
        "checksum": None,
        "expected_checksum": None,
        "message_valid": False,
        "validation_errors": ";".join(f"{field}:{kind}" for field, kind, _ in errors),
        "source": "TeachingLink",
        "_error_items": errors,
        "_frame_error_items": errors,
        "_field_error_items": [],
    }


def _flag_value_errors(validity: int, callsign_bytes: bytes, codes: dict[str, int]) -> list[tuple[str, str, str]]:
    """检查有效位与占位值是否一致，并验证呼号的零填充位置。

    有效位为 0 时，对应字节必须全为 0；否则接收端无法判断发送方究竟想表达
    “缺失”还是一个被错误隐藏的数值。呼号有效时，中间不能出现 0 后又出现字符，
    因为协议只允许有效 ASCII 内容之后进行尾部补零。
    """
    errors: list[tuple[str, str, str]] = []
    for field, bit in VALIDITY_BITS.items():
        valid = bool(validity & (1 << bit))
        value = callsign_bytes if field == "callsign" else codes[field]
        if not valid and value != (b"\x00" * 8 if field == "callsign" else 0):
            errors.append((field, "FLAG_VALUE_INCONSISTENCY", "有效位为 0 时占位字段必须为 0。"))
        if field == "callsign" and valid and (not callsign_bytes.rstrip(b"\x00") or b"\x00" in callsign_bytes.rstrip(b"\x00")):
            errors.append((field, "FLAG_VALUE_INCONSISTENCY", "有效呼号必须是连续的非空 ASCII 字节，后部才可填充 0。"))
    return errors


def decode_position_message(data: bytes) -> dict[str, Any]:
    """验证 41 字节帧并恢复接收方结构化记录。

    接收端不会因为发现第一个错误就抛异常退出，而是尽量收集同一帧中的全部
    可判断问题，并通过 ``message_valid=False`` 和 ``_error_items`` 返回。
    这样上层可以将坏帧写入 validation_log.csv，同时继续处理后续帧。
    """
    frame_errors: list[tuple[str, str, str]] = []
    field_errors: list[tuple[str, str, str]] = []

    # 类型或总长度不正确时，后续固定偏移均不再可信，直接返回统一空结果。
    if not isinstance(data, (bytes, bytearray)):
        return _empty_decoded([("frame", "TYPE_ERROR", "接收数据必须是 bytes 或 bytearray。")] )
    raw = bytes(data)
    if len(raw) != FRAME_SIZE:
        return _empty_decoded([("frame", "LENGTH_ERROR", f"实际帧长度为 {len(raw)}，要求为 41。")])

    # 先读取固定帧头和尾部校验和。即使某一字段错误，也继续检查其他字段，
    # 以便一次性给出更完整的接收诊断。
    magic = int.from_bytes(raw[0:2], "big")
    version = raw[2]
    message_type = raw[3]
    message_length = int.from_bytes(raw[4:6], "big")
    timestamp = int.from_bytes(raw[8:12], "big")
    checksum = int.from_bytes(raw[39:41], "big")
    expected_checksum = calculate_checksum(raw[:39])
    if magic != MAGIC:
        frame_errors.append(("magic", "MAGIC_ERROR", "magic 必须为 0x4453。"))
    if version != VERSION:
        frame_errors.append(("version", "VERSION_ERROR", "version 必须为 1。"))
    if message_type != MESSAGE_TYPE:
        frame_errors.append(("message_type", "MESSAGE_TYPE_ERROR", "message_type 必须为 1。"))
    if message_length != FRAME_SIZE:
        frame_errors.append(("message_length", "LENGTH_ERROR", "帧内 message_length 必须为 41。"))
    if timestamp == 0:
        frame_errors.append(("timestamp", "REQUIRED_FIELD_MISSING", "接收帧 timestamp 必须为可用的非零 Unix 秒时间戳。"))
    if checksum != expected_checksum:
        frame_errors.append(("checksum", "CHECKSUM_ERROR", "checksum 与前 39 字节重算结果不一致。"))

    # 经纬度使用 3 字节容器但只允许低 22 位有效；最高 2 位出现 1 表明
    # 发送端编码错误或传输数据被破坏。
    latitude_code = int.from_bytes(raw[23:26], "big")
    longitude_code = int.from_bytes(raw[26:29], "big")
    if latitude_code & 0xC00000:
        frame_errors.append(("latitude_code", "RESERVED_BITS_ERROR", "纬度容器最高 2 位必须为 0。"))
    if longitude_code & 0xC00000:
        frame_errors.append(("longitude_code", "RESERVED_BITS_ERROR", "经度容器最高 2 位必须为 0。"))

    # 两个标志字节均有保留位。当前协议版本中保留位必须为 0，不能忽略，
    # 否则不同版本可能把未知语义误当成当前版本的合法帧。
    status_flags = raw[37]
    validity_flags = raw[38]
    if status_flags & 0xF8:
        frame_errors.append(("status_flags", "RESERVED_BITS_ERROR", "status_flags 的 bit3-bit7 必须为 0。"))
    if validity_flags & 0x80:
        frame_errors.append(("validity_flags", "RESERVED_BITS_ERROR", "validity_flags 的 bit7 必须为 0。"))

    # 先保留原始协议整数，再根据 validity_flags 决定是否反量化为物理值。
    # 输出同时包含协议码和物理值，便于实验审计与往返误差分析。
    codes = {
        "lat": latitude_code,
        "lon": longitude_code,
        "altitude": int.from_bytes(raw[29:31], "big"),
        "speed": int.from_bytes(raw[31:33], "big"),
        "heading": int.from_bytes(raw[33:35], "big"),
        "vertical_rate": int.from_bytes(raw[35:37], "big"),
    }
    callsign_bytes = raw[15:23]
    frame_errors.extend(_flag_value_errors(validity_flags, callsign_bytes, codes))

    # 将位图展开为按字段命名的布尔值，避免后续恢复每个字段时重复位运算。
    valid = {field: bool(validity_flags & (1 << bit)) for field, bit in VALIDITY_BITS.items()}
    # 航向字段虽然使用 uint16 容器，但协议只允许 0-35999。检查协议码而不是
    # 只检查容器位宽，防止带有合法 checksum 的 360.00 度或更大航向混入。
    if valid["heading"] and codes["heading"] > MAX_HEADING_CODE:
        field_errors.append(("heading_code", "OUT_OF_RANGE", "航向协议码越界；该字段按无效处理。"))
        valid["heading"] = False
    target_id = f"{int.from_bytes(raw[12:15], 'big'):06x}"
    callsign: str | None = None
    if valid["callsign"]:
        try:
            callsign = callsign_bytes.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            field_errors.append(("callsign", "ENCODING_ERROR", "callsign 不能按 ASCII 解码；该字段按无效处理。"))
            valid["callsign"] = False
    # 只有有效位为 1 才反量化。协议码为 0 且有效位为 1 时仍是合法真实值；
    # 有效位为 0 时无论占位区如何，都不会把 0 误解释成物理量。
    lat = codes["lat"] / MAX_22BIT * 180.0 - 90.0 if valid["lat"] else None
    lon = codes["lon"] / MAX_22BIT * 360.0 - 180.0 if valid["lon"] else None
    altitude = codes["altitude"] - 1000.0 if valid["altitude"] else None
    speed = codes["speed"] * 0.1 if valid["speed"] else None
    heading = codes["heading"] * 0.01 if valid["heading"] else None
    vertical_rate = codes["vertical_rate"] * 0.01 - 327.68 if valid["vertical_rate"] else None

    # message_valid 只汇总完整帧接收判据。可选字段语义错误被降级为空并记录，
    # 不自动把整个帧改为无效；_error_items 供上层统一写 validation_log.csv。
    all_errors = frame_errors + field_errors
    return {
        "target_id": target_id,
        "callsign": callsign,
        "timestamp": timestamp,
        "timestamp_source": "last_contact_fallback" if status_flags & 0x04 else "position_time",
        "time_source": "last_contact_fallback" if status_flags & 0x04 else "position_time",
        "message_seq": int.from_bytes(raw[6:8], "big"),
        "lat": lat,
        "lon": lon,
        "altitude": altitude,
        "alt_type": "geometric" if valid["altitude"] and status_flags & 0x02 else "barometric" if valid["altitude"] else "unknown",
        "speed": speed,
        "heading": heading,
        "vertical_rate": vertical_rate,
        "on_ground": bool(status_flags & 0x01),
        "status_flags": status_flags,
        "validity_flags": validity_flags,
        "latitude_code": codes["lat"],
        "longitude_code": codes["lon"],
        "altitude_code": codes["altitude"],
        "speed_code": codes["speed"],
        "heading_code": codes["heading"],
        "vertical_rate_code": codes["vertical_rate"],
        "lat_valid": valid["lat"],
        "lon_valid": valid["lon"],
        "altitude_valid": valid["altitude"],
        "speed_valid": valid["speed"],
        "heading_valid": valid["heading"],
        "vertical_rate_valid": valid["vertical_rate"],
        "callsign_valid": valid["callsign"],
        "checksum": checksum,
        "expected_checksum": expected_checksum,
        "message_valid": not frame_errors,
        "validation_errors": ";".join(f"{field}:{kind}" for field, kind, _ in all_errors),
        "source": "TeachingLink",
        "_error_items": all_errors,
        "_frame_error_items": frame_errors,
        "_field_error_items": field_errors,
    }


# 三个 CSV 的列顺序由课程模板固定。集中定义可以防止写出时漏列、乱序，
# 也让 csv.DictWriter 自动过滤仅供内部使用的 _error_items 等辅助字段。
DECODED_FIELDS = [
    "target_id", "callsign", "timestamp", "timestamp_source", "time_source", "message_seq", "lat", "lon",
    "altitude", "alt_type", "speed", "heading", "vertical_rate", "on_ground", "status_flags", "validity_flags",
    "latitude_code", "longitude_code", "altitude_code", "speed_code", "heading_code", "vertical_rate_code",
    "lat_valid", "lon_valid", "altitude_valid", "speed_valid", "heading_valid", "vertical_rate_valid",
    "callsign_valid", "checksum", "expected_checksum", "message_valid", "validation_errors", "source",
]
LOG_FIELDS = ["record_no", "target_id", "stage", "field", "problem_type", "value", "description"]
ROUNDTRIP_FIELDS = ["field", "source_value", "source_valid", "protocol_code", "flag_bit", "decoded_value", "decoded_valid", "absolute_error/tolerance", "passed"]


def _as_csv_value(value: Any) -> Any:
    """将内部 ``None`` 转为空单元格，同时保留数值 0 和布尔 False。"""
    return "" if value is None else value


def _log(logs: list[dict[str, Any]], record_no: Any, target_id: Any, stage: str, error: ProtocolError) -> None:
    """把发送端抛出的结构化 ``ProtocolError`` 追加为一条课程格式日志。"""
    logs.append({
        "record_no": record_no,
        "target_id": _as_csv_value(target_id),
        "stage": stage,
        "field": error.field,
        "problem_type": error.problem_type,
        "value": _as_csv_value(error.value),
        "description": error.description,
    })


def _log_decoding_errors(logs: list[dict[str, Any]], record_no: Any, target_id: Any, decoded: dict[str, Any]) -> None:
    """把接收端一次收集到的多个帧错误逐条展开到 validation_log.csv。"""
    for field, kind, description in decoded["_error_items"]:
        logs.append({
            "record_no": record_no,
            "target_id": _as_csv_value(target_id),
            "stage": "receive_validation",
            "field": field,
            "problem_type": kind,
            "value": "",
            "description": description,
        })


def _roundtrip_rows(source: dict[str, Any], decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """比较一条记录编码前后的七个可空字段。

    数值字段容许的最大误差取手册规定的一个量化单位；呼号是离散文本，必须
    完全一致。缺失字段重点比较两端有效位和 ``None``，不能把占位零当作源值。
    """
    # 每项给出：物理字段、对应协议码字段、有效位编号、允许误差。
    definitions = [
        ("lat", "latitude_code", VALIDITY_BITS["lat"], 180.0 / MAX_22BIT),
        ("lon", "longitude_code", VALIDITY_BITS["lon"], 360.0 / MAX_22BIT),
        ("altitude", "altitude_code", VALIDITY_BITS["altitude"], 1.0),
        ("speed", "speed_code", VALIDITY_BITS["speed"], 0.1),
        ("heading", "heading_code", VALIDITY_BITS["heading"], 0.01),
        ("vertical_rate", "vertical_rate_code", VALIDITY_BITS["vertical_rate"], 0.01),
        ("callsign", "callsign", VALIDITY_BITS["callsign"], None),
    ]
    rows: list[dict[str, Any]] = []
    for field, code_field, bit, tolerance in definitions:
        source_value = source[field]
        decoded_value = decoded[field]
        source_valid = source_value is not None
        decoded_valid = bool(decoded[f"{field}_valid"])
        # 呼号没有数值误差概念；其文本、源有效性和解码有效性必须全部一致。
        if tolerance is None:
            error_text = "0/0" if source_value == decoded_value else "不适用/0"
            passed = source_valid == decoded_valid and source_value == decoded_value
        # 数值两端均有效时计算绝对误差，并与一个最小量化单位比较。
        elif source_valid and decoded_valid:
            error = abs(float(source_value) - float(decoded_value))
            error_text = f"{error:.12g}/{tolerance:.12g}"
            passed = error <= tolerance
        # 任一端无效时不做数值运算，只检查双方是否都正确表达了“缺失”。
        else:
            error_text = "0/0"
            passed = source_valid == decoded_valid and decoded_value is None
        rows.append({
            "field": field,
            "source_value": _as_csv_value(source_value),
            "source_valid": source_valid,
            "protocol_code": _as_csv_value(decoded.get(code_field)),
            "flag_bit": bit,
            "decoded_value": _as_csv_value(decoded_value),
            "decoded_valid": decoded_valid,
            "absolute_error/tolerance": error_text,
            "passed": passed,
        })
    return rows


def _rechecksum(frame: bytearray) -> bytes:
    """修改测试帧后重算校验和，使测试只命中预期的非校验和错误。"""
    frame[39:41] = calculate_checksum(bytes(frame[:39])).to_bytes(2, "big")
    return bytes(frame)


def _error_frames(frame: bytes) -> list[tuple[str, bytes]]:
    """从一条合法帧派生覆盖各接收判据的十二种错误。

    除专门测试 checksum 的帧外，修改字段后都会重新计算校验和，避免一个
    magic 或保留位测试同时被无意标记成 CHECKSUM_ERROR。这些坏帧只送入
    解码器验证错误处理，绝不会写入正常的 encoded_messages.bin。
    """
    # 每个副本只破坏一个检查点，便于确认接收端报告的 problem_type 是否准确。
    bad_magic = bytearray(frame)
    bad_magic[0] ^= 0x01
    bad_version = bytearray(frame)
    bad_version[2] = 2
    bad_type = bytearray(frame)
    bad_type[3] = 2
    bad_message_length = bytearray(frame)
    bad_message_length[4:6] = (40).to_bytes(2, "big")
    missing_timestamp = bytearray(frame)
    missing_timestamp[8:12] = b"\x00" * 4
    bad_checksum = bytearray(frame)
    bad_checksum[40] ^= 0x01
    bad_latitude_reserved = bytearray(frame)
    bad_latitude_reserved[23] |= 0x80
    bad_longitude_reserved = bytearray(frame)
    bad_longitude_reserved[26] |= 0x80
    bad_status_reserved = bytearray(frame)
    bad_status_reserved[37] |= 0x08
    bad_validity_reserved = bytearray(frame)
    bad_validity_reserved[38] |= 0x80
    bad_flags = bytearray(frame)
    bad_flags[38] &= ~(1 << VALIDITY_BITS["lat"])
    return [
        ("test_length", frame[:-1]),
        ("test_magic", _rechecksum(bad_magic)),
        ("test_version", _rechecksum(bad_version)),
        ("test_message_type", _rechecksum(bad_type)),
        ("test_message_length", _rechecksum(bad_message_length)),
        ("test_required_timestamp", _rechecksum(missing_timestamp)),
        ("test_checksum", bytes(bad_checksum)),
        ("test_latitude_reserved_bits", _rechecksum(bad_latitude_reserved)),
        ("test_longitude_reserved_bits", _rechecksum(bad_longitude_reserved)),
        ("test_status_reserved_bits", _rechecksum(bad_status_reserved)),
        ("test_validity_reserved_bits", _rechecksum(bad_validity_reserved)),
        ("test_flag_value", _rechecksum(bad_flags)),
    ]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    """按课程模板列顺序写出 UTF-8 BOM CSV，便于 Windows Excel 查看。"""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_m2(project_root: Path | None = None) -> dict[str, int]:
    """批量执行完整 M2 流程，并返回便于核对的数量摘要。

    执行顺序是：定位课程包 → 读取 states 数组 → 逐条解析和编码 → 接收端
    校验与解码 → 生成往返误差 → 注入坏帧测试 → 写出四项规定成果。
    默认从本文件位置推导项目根目录，测试时也可以显式传入 ``project_root``。
    """
    root = project_root or Path(__file__).resolve().parents[2]
    package = root / "student_package"
    output = package / "output"
    output.mkdir(parents=True, exist_ok=True)
    # 原始教学数据保持只读；所有新成果统一进入 output 目录。
    raw = json.loads((package / "data" / "raw_states.json").read_text(encoding="utf-8"))
    states = raw.get("states")
    if not isinstance(states, list):
        raise ValueError("raw_states.json 缺少 states 数组。")

    # 各列表先在内存中累积，全部处理结束后一次写出，结构更容易核对。
    frames: list[bytes] = []
    decoded_rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    roundtrip_rows: list[dict[str, Any]] = []
    sequence = 1

    for record_no, vector in enumerate(states, start=1):
        # target_hint 只用于解析失败时尽量在日志中标出原目标；即使数组本身
        # 不完整，也不能因为生成日志再次抛异常。
        target_hint = vector[0] if isinstance(vector, list) and vector else ""
        try:
            record = parse_state_vector(vector)
            field_errors = list(record.pop("_field_errors", []))
            frame = encode_position_message(record, sequence, field_errors)
        except ProtocolError as error:
            # 到这里的错误来自必需字段或帧骨架，无法生成正常帧。
            _log(logs, record_no, target_hint, "parse_or_encode", error)
            continue

        # 可选字段错误已经被降级为缺失；逐项记录后仍继续封装该帧。
        for error in field_errors:
            _log(logs, record_no, record["target_id"], "optional_field_validation", error)

        # 对自己刚编码的帧也走完整接收流程，验证发送端和接收端确实互通。
        decoded = decode_position_message(frame)
        if decoded["_error_items"]:
            _log_decoding_errors(logs, record_no, record["target_id"], decoded)
        if not decoded["message_valid"]:
            continue
        # 只有成功通过接收检查的正常帧才进入正式成果和往返误差报告。
        frames.append(frame)
        decoded_rows.append(decoded)
        roundtrip_rows.extend(_roundtrip_rows(record, decoded))
        sequence += 1

    # 至少有一条正常帧时，以第一帧为基准构造坏帧，验证各类接收错误。
    if frames:
        for test_name, test_frame in _error_frames(frames[0]):
            decoded = decode_position_message(test_frame)
            _log_decoding_errors(logs, test_name, decoded.get("target_id", ""), decoded)

    # 二进制文件直接顺序拼接固定 41 字节帧，不额外添加分隔符或文件头。
    (output / "encoded_messages.bin").write_bytes(b"".join(frames))
    _write_csv(output / "decoded_partner_states.csv", DECODED_FIELDS, decoded_rows)
    _write_csv(output / "validation_log.csv", LOG_FIELDS, logs)
    _write_csv(output / "roundtrip_report.csv", ROUNDTRIP_FIELDS, roundtrip_rows)
    return {"encoded_frames": len(frames), "decoded_rows": len(decoded_rows), "validation_rows": len(logs), "roundtrip_rows": len(roundtrip_rows)}


if __name__ == "__main__":
    # 只有直接运行本文件时才执行实验；被 M3/M6 或测试代码导入时不会自动写文件。
    result = run_m2()
    print("M2 完成：" + "，".join(f"{name}={count}" for name, count in result.items()))
