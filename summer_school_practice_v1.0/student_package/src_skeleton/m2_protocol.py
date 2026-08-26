from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


FRAME_SIZE = 41
MAGIC = 0x4453
VERSION = 1
MESSAGE_TYPE = 1
MAX_22BIT = (1 << 22) - 1

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
    """携带课程规定错误类型的可记录异常。"""

    def __init__(self, field: str, problem_type: str, value: Any, description: str) -> None:
        super().__init__(description)
        self.field = field
        self.problem_type = problem_type
        self.value = value
        self.description = description


def _problem(field: str, problem_type: str, value: Any, description: str) -> ProtocolError:
    return ProtocolError(field, problem_type, value, description)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(field: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _problem(field, "TYPE_ERROR", value, "字段必须是有限数值。")
    number = float(value)
    if not math.isfinite(number):
        raise _problem(field, "TYPE_ERROR", value, "字段必须是有限数值。")
    return number


def _nullable_number(field: str, value: Any, low: float, high: float) -> float | None:
    if value is None:
        return None
    number = _finite_number(field, value)
    if not low <= number <= high:
        raise _problem(field, "OUT_OF_RANGE", value, f"字段量程必须在 [{low}, {high}] 内。")
    return number


def _target_id(value: Any) -> str:
    if not isinstance(value, str):
        raise _problem("target_id", "TYPE_ERROR", value, "target_id 必须是六位十六进制字符串。")
    target = value.lower()
    if len(target) != 6 or any(char not in "0123456789abcdef" for char in target):
        raise _problem("target_id", "OUT_OF_RANGE", value, "target_id 必须恰好为六位十六进制字符串。")
    return target


def _callsign(value: Any) -> str | None:
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
    if not _is_integer(value) or not 0 <= value <= 0xFFFFFFFF:
        raise _problem("timestamp", "OUT_OF_RANGE", value, "timestamp 必须是 uint32 范围内的整数。")
    return value


def _quantize(value: float) -> int:
    """课程规定的 Q(y)=floor(y+0.5)，不依赖 Python round。"""
    return math.floor(value + 0.5)


def parse_state_vector(vector: list[Any]) -> dict[str, Any]:
    """将 OpenSky 状态向量转换为发送方内部结构化记录。"""
    if not isinstance(vector, list) or len(vector) <= 13:
        raise _problem("state_vector", "LENGTH_ERROR", vector, "状态向量长度不足，无法读取 M2 所需字段。")

    target = _target_id(vector[0])
    position_time, last_contact = vector[3], vector[4]
    if position_time is not None:
        timestamp = _timestamp(position_time)
        timestamp_source = "position_time"
    elif last_contact is not None:
        timestamp = _timestamp(last_contact)
        timestamp_source = "last_contact_fallback"
    else:
        raise _problem("timestamp", "REQUIRED_FIELD_MISSING", None, "time_position 与 last_contact 均为空。")

    on_ground = vector[8]
    if not isinstance(on_ground, bool):
        raise _problem("on_ground", "TYPE_ERROR", on_ground, "on_ground 必须是布尔值。")

    baro_altitude, geo_altitude = vector[7], vector[13]
    if baro_altitude is not None:
        altitude = _nullable_number("altitude", baro_altitude, -1000.0, 64535.0)
        alt_type = "barometric"
    elif geo_altitude is not None:
        altitude = _nullable_number("altitude", geo_altitude, -1000.0, 64535.0)
        alt_type = "geometric"
    else:
        altitude = None
        alt_type = "unknown"

    return {
        "target_id": target,
        "callsign": _callsign(vector[1]),
        "timestamp": timestamp,
        "timestamp_source": timestamp_source,
        "lat": _nullable_number("lat", vector[6], -90.0, 90.0),
        "lon": _nullable_number("lon", vector[5], -180.0, 180.0),
        "altitude": altitude,
        "alt_type": alt_type,
        "speed": _nullable_number("speed", vector[9], 0.0, 6553.5),
        "heading": _nullable_number("heading", vector[10], 0.0, math.nextafter(360.0, -math.inf)),
        "vertical_rate": _nullable_number("vertical_rate", vector[11], -327.68, 327.67),
        "on_ground": on_ground,
    }


def calculate_checksum(data_without_checksum: bytes) -> int:
    """计算前 39 字节无符号字节值之和模 65536。"""
    return sum(data_without_checksum) % 65536


def _encode_optional(frame: bytearray, offset: int, width: int, code: int | None, bit: int, validity: int) -> int:
    if code is None:
        return validity
    if not 0 <= code < (1 << (width * 8)):
        raise _problem("protocol_code", "ENCODING_ERROR", code, "协议整数超出字段位宽。")
    frame[offset : offset + width] = code.to_bytes(width, "big")
    return validity | (1 << bit)


def encode_position_message(record: dict[str, Any], message_seq: int) -> bytes:
    """按 41 字节 TeachingLink 格式封装一条位置状态消息。"""
    if not isinstance(record, dict):
        raise _problem("record", "TYPE_ERROR", record, "发送记录必须是字典。")
    if not _is_integer(message_seq) or message_seq < 0:
        raise _problem("message_seq", "TYPE_ERROR", message_seq, "message_seq 必须是非负整数。")

    target = _target_id(record.get("target_id"))
    timestamp = _timestamp(record.get("timestamp"))
    on_ground = record.get("on_ground")
    if not isinstance(on_ground, bool):
        raise _problem("on_ground", "TYPE_ERROR", on_ground, "on_ground 必须是布尔值。")

    callsign = _callsign(record.get("callsign"))
    lat = _nullable_number("lat", record.get("lat"), -90.0, 90.0)
    lon = _nullable_number("lon", record.get("lon"), -180.0, 180.0)
    altitude = _nullable_number("altitude", record.get("altitude"), -1000.0, 64535.0)
    speed = _nullable_number("speed", record.get("speed"), 0.0, 6553.5)
    heading = _nullable_number("heading", record.get("heading"), 0.0, math.nextafter(360.0, -math.inf))
    vertical_rate = _nullable_number("vertical_rate", record.get("vertical_rate"), -327.68, 327.67)

    frame = bytearray(FRAME_SIZE)
    frame[0:2] = MAGIC.to_bytes(2, "big")
    frame[2] = VERSION
    frame[3] = MESSAGE_TYPE
    frame[4:6] = FRAME_SIZE.to_bytes(2, "big")
    frame[6:8] = (message_seq % 65536).to_bytes(2, "big")
    frame[8:12] = timestamp.to_bytes(4, "big")
    frame[12:15] = int(target, 16).to_bytes(3, "big")

    validity = 0
    if callsign is not None:
        raw_callsign = callsign.encode("ascii")
        frame[15:23] = raw_callsign.ljust(8, b"\x00")
        validity |= 1 << VALIDITY_BITS["callsign"]

    latitude_code = None if lat is None else _quantize((lat + 90.0) / 180.0 * MAX_22BIT)
    longitude_code = None if lon is None else _quantize((lon + 180.0) / 360.0 * MAX_22BIT)
    altitude_code = None if altitude is None else _quantize(altitude + 1000.0)
    speed_code = None if speed is None else _quantize(speed / 0.1)
    heading_code = None if heading is None else _quantize(heading / 0.01)
    vertical_rate_code = None if vertical_rate is None else _quantize((vertical_rate + 327.68) / 0.01)

    validity = _encode_optional(frame, 23, 3, latitude_code, VALIDITY_BITS["lat"], validity)
    validity = _encode_optional(frame, 26, 3, longitude_code, VALIDITY_BITS["lon"], validity)
    validity = _encode_optional(frame, 29, 2, altitude_code, VALIDITY_BITS["altitude"], validity)
    validity = _encode_optional(frame, 31, 2, speed_code, VALIDITY_BITS["speed"], validity)
    validity = _encode_optional(frame, 33, 2, heading_code, VALIDITY_BITS["heading"], validity)
    validity = _encode_optional(frame, 35, 2, vertical_rate_code, VALIDITY_BITS["vertical_rate"], validity)

    status = int(on_ground)
    if record.get("alt_type") == "geometric":
        status |= 1 << 1
    if record.get("timestamp_source") == "last_contact_fallback":
        status |= 1 << 2
    frame[37] = status
    frame[38] = validity
    frame[39:41] = calculate_checksum(bytes(frame[:39])).to_bytes(2, "big")
    return bytes(frame)


def _empty_decoded(errors: list[tuple[str, str, str]]) -> dict[str, Any]:
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
    }


def _flag_value_errors(validity: int, callsign_bytes: bytes, codes: dict[str, int]) -> list[tuple[str, str, str]]:
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
    """检查帧接收条件并恢复接收方结构化记录；非法帧返回 message_valid=False。"""
    errors: list[tuple[str, str, str]] = []
    if not isinstance(data, (bytes, bytearray)):
        return _empty_decoded([("frame", "TYPE_ERROR", "接收数据必须是 bytes 或 bytearray。")] )
    raw = bytes(data)
    if len(raw) != FRAME_SIZE:
        return _empty_decoded([("frame", "LENGTH_ERROR", f"实际帧长度为 {len(raw)}，要求为 41。")])

    magic = int.from_bytes(raw[0:2], "big")
    version = raw[2]
    message_type = raw[3]
    message_length = int.from_bytes(raw[4:6], "big")
    checksum = int.from_bytes(raw[39:41], "big")
    expected_checksum = calculate_checksum(raw[:39])
    if magic != MAGIC:
        errors.append(("magic", "MAGIC_ERROR", "magic 必须为 0x4453。"))
    if version != VERSION:
        errors.append(("version", "VERSION_ERROR", "version 必须为 1。"))
    if message_type != MESSAGE_TYPE:
        errors.append(("message_type", "MESSAGE_TYPE_ERROR", "message_type 必须为 1。"))
    if message_length != FRAME_SIZE:
        errors.append(("message_length", "LENGTH_ERROR", "帧内 message_length 必须为 41。"))
    if checksum != expected_checksum:
        errors.append(("checksum", "CHECKSUM_ERROR", "checksum 与前 39 字节重算结果不一致。"))

    latitude_code = int.from_bytes(raw[23:26], "big")
    longitude_code = int.from_bytes(raw[26:29], "big")
    if latitude_code & 0xC00000:
        errors.append(("latitude_code", "RESERVED_BITS_ERROR", "纬度容器最高 2 位必须为 0。"))
    if longitude_code & 0xC00000:
        errors.append(("longitude_code", "RESERVED_BITS_ERROR", "经度容器最高 2 位必须为 0。"))

    status_flags = raw[37]
    validity_flags = raw[38]
    if status_flags & 0xF8:
        errors.append(("status_flags", "RESERVED_BITS_ERROR", "status_flags 的 bit3-bit7 必须为 0。"))
    if validity_flags & 0x80:
        errors.append(("validity_flags", "RESERVED_BITS_ERROR", "validity_flags 的 bit7 必须为 0。"))

    codes = {
        "lat": latitude_code,
        "lon": longitude_code,
        "altitude": int.from_bytes(raw[29:31], "big"),
        "speed": int.from_bytes(raw[31:33], "big"),
        "heading": int.from_bytes(raw[33:35], "big"),
        "vertical_rate": int.from_bytes(raw[35:37], "big"),
    }
    callsign_bytes = raw[15:23]
    errors.extend(_flag_value_errors(validity_flags, callsign_bytes, codes))

    valid = {field: bool(validity_flags & (1 << bit)) for field, bit in VALIDITY_BITS.items()}
    target_id = f"{int.from_bytes(raw[12:15], 'big'):06x}"
    callsign: str | None = None
    if valid["callsign"]:
        try:
            callsign = callsign_bytes.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            errors.append(("callsign", "ENCODING_ERROR", "callsign 不能按 ASCII 解码。"))
    lat = codes["lat"] / MAX_22BIT * 180.0 - 90.0 if valid["lat"] else None
    lon = codes["lon"] / MAX_22BIT * 360.0 - 180.0 if valid["lon"] else None
    altitude = codes["altitude"] - 1000.0 if valid["altitude"] else None
    speed = codes["speed"] * 0.1 if valid["speed"] else None
    heading = codes["heading"] * 0.01 if valid["heading"] else None
    vertical_rate = codes["vertical_rate"] * 0.01 - 327.68 if valid["vertical_rate"] else None

    return {
        "target_id": target_id,
        "callsign": callsign,
        "timestamp": int.from_bytes(raw[8:12], "big"),
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
        "message_valid": not errors,
        "validation_errors": ";".join(f"{field}:{kind}" for field, kind, _ in errors),
        "source": "TeachingLink",
        "_error_items": errors,
    }


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
    return "" if value is None else value


def _log(logs: list[dict[str, Any]], record_no: Any, target_id: Any, stage: str, error: ProtocolError) -> None:
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
        if tolerance is None:
            error_text = "0/0" if source_value == decoded_value else "不适用/0"
            passed = source_valid == decoded_valid and source_value == decoded_value
        elif source_valid and decoded_valid:
            error = abs(float(source_value) - float(decoded_value))
            error_text = f"{error:.12g}/{tolerance:.12g}"
            passed = error <= tolerance
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
    frame[39:41] = calculate_checksum(bytes(frame[:39])).to_bytes(2, "big")
    return bytes(frame)


def _error_frames(frame: bytes) -> list[tuple[str, bytes]]:
    """构造手册要求的帧级错误，不写入 encoded_messages.bin。"""
    bad_magic = bytearray(frame)
    bad_magic[0] ^= 0x01
    bad_version = bytearray(frame)
    bad_version[2] = 2
    bad_type = bytearray(frame)
    bad_type[3] = 2
    bad_checksum = bytearray(frame)
    bad_checksum[40] ^= 0x01
    bad_reserved = bytearray(frame)
    bad_reserved[23] |= 0x80
    bad_flags = bytearray(frame)
    bad_flags[38] &= ~(1 << VALIDITY_BITS["lat"])
    return [
        ("test_length", frame[:-1]),
        ("test_magic", _rechecksum(bad_magic)),
        ("test_version", _rechecksum(bad_version)),
        ("test_message_type", _rechecksum(bad_type)),
        ("test_checksum", bytes(bad_checksum)),
        ("test_reserved_bits", _rechecksum(bad_reserved)),
        ("test_flag_value", _rechecksum(bad_flags)),
    ]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_m2(project_root: Path | None = None) -> dict[str, int]:
    """批量处理 raw_states.json，并生成 M2 规定的四项结果。"""
    root = project_root or Path(__file__).resolve().parents[2]
    package = root / "student_package"
    output = package / "output"
    output.mkdir(parents=True, exist_ok=True)
    raw = json.loads((package / "data" / "raw_states.json").read_text(encoding="utf-8"))
    states = raw.get("states")
    if not isinstance(states, list):
        raise ValueError("raw_states.json 缺少 states 数组。")

    frames: list[bytes] = []
    decoded_rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    roundtrip_rows: list[dict[str, Any]] = []
    sequence = 1

    for record_no, vector in enumerate(states, start=1):
        target_hint = vector[0] if isinstance(vector, list) and vector else ""
        try:
            record = parse_state_vector(vector)
            frame = encode_position_message(record, sequence)
        except ProtocolError as error:
            _log(logs, record_no, target_hint, "parse_or_encode", error)
            continue

        decoded = decode_position_message(frame)
        if not decoded["message_valid"]:
            _log_decoding_errors(logs, record_no, record["target_id"], decoded)
            continue
        frames.append(frame)
        decoded_rows.append(decoded)
        roundtrip_rows.extend(_roundtrip_rows(record, decoded))
        sequence += 1

    if frames:
        for test_name, test_frame in _error_frames(frames[0]):
            decoded = decode_position_message(test_frame)
            _log_decoding_errors(logs, test_name, decoded.get("target_id", ""), decoded)

    (output / "encoded_messages.bin").write_bytes(b"".join(frames))
    _write_csv(output / "decoded_partner_states.csv", DECODED_FIELDS, decoded_rows)
    _write_csv(output / "validation_log.csv", LOG_FIELDS, logs)
    _write_csv(output / "roundtrip_report.csv", ROUNDTRIP_FIELDS, roundtrip_rows)
    return {"encoded_frames": len(frames), "decoded_rows": len(decoded_rows), "validation_rows": len(logs), "roundtrip_rows": len(roundtrip_rows)}


if __name__ == "__main__":
    result = run_m2()
    print("M2 完成：" + "，".join(f"{name}={count}" for name, count in result.items()))
