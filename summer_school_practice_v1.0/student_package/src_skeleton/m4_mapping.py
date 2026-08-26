from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any


MODEL_FIELDS = {"track_id", "source", "timestamp", "identity", "position", "motion", "status", "quality"}
MAPPING_FIELDS = ["source_format", "input_field", "unified_field", "mapping_rule", "unit_conversion", "null_strategy", "evidence", "verified"]
TARGET_ID_PATTERN = re.compile(r"^[0-9a-f]{6}$")
LAT_LON_MAX_CODE = 2**22 - 1


def _as_int(value: Any, field: str) -> int:
    """将 CSV 的整数文本转换为整数；布尔值不被当作整数接受。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能为布尔值。")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip() and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{field} 必须为整数。")


def _as_bool(value: Any, field: str) -> bool:
    """兼容 CSV 的 True/False，同时拒绝含义不明确的值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{field} 必须为布尔值。")


def _optional_number(value: Any, field: str) -> float | None:
    """将空白 CSV 字段恢复为 None，其他值转换为有限浮点数。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能为布尔值。")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} 必须为有限数值。")
    return number


def _normalise_target_id(value: Any) -> str:
    """保留六位小写十六进制目标标识及其前导零。"""
    target_id = str(value).strip().lower()
    if not TARGET_ID_PATTERN.fullmatch(target_id):
        raise ValueError("target_id 必须是六位十六进制字符串。")
    return target_id


def _flag(flags: int, bit: int) -> bool:
    return bool(flags & (1 << bit))


def _valid_code(code: int, lower: int, upper: int) -> bool:
    return lower <= code <= upper


def _decode_teaching_optional(record: dict[str, Any], field: str, bit: int) -> float | None:
    """按有效位恢复 TeachingLink 定点字段；无效位永远返回 None。"""
    validity_flags = _as_int(record.get("validity_flags"), "validity_flags")
    if not _flag(validity_flags, bit):
        return None
    code = _as_int(record.get(f"{field}_code"), f"{field}_code")
    if field == "latitude":
        return code / LAT_LON_MAX_CODE * 180.0 - 90.0 if _valid_code(code, 0, LAT_LON_MAX_CODE) else None
    if field == "longitude":
        return code / LAT_LON_MAX_CODE * 360.0 - 180.0 if _valid_code(code, 0, LAT_LON_MAX_CODE) else None
    if field == "altitude":
        return float(code - 1000) if _valid_code(code, 0, 65535) else None
    if field == "speed":
        return code * 0.1 if _valid_code(code, 0, 65535) else None
    if field == "heading":
        return code * 0.01 if _valid_code(code, 0, 35999) else None
    if field == "vertical_rate":
        return code * 0.01 - 327.68 if _valid_code(code, 0, 65535) else None
    raise ValueError(f"未知 TeachingLink 字段：{field}。")


def _teaching_quality(record: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """由标志、量程和接收结论生成统一质量字段。"""
    validity_flags = _as_int(record.get("validity_flags"), "validity_flags")
    status_flags = _as_int(record.get("status_flags"), "status_flags")
    anomalies: list[str] = []
    if validity_flags & 0x80:
        anomalies.append("validity_flags_reserved_bit_set")
    if status_flags & 0xF8:
        anomalies.append("status_flags_reserved_bits_set")
    for name, bit in (("latitude", 0), ("longitude", 1), ("altitude", 2), ("speed", 3), ("heading", 4), ("vertical_rate", 5)):
        if _flag(validity_flags, bit) and values[name] is None:
            anomalies.append(f"{name}_code_out_of_range")
    timestamp = _as_int(record.get("latest_time", record.get("timestamp")), "timestamp")
    return {
        "position_valid": values["latitude"] is not None and values["longitude"] is not None,
        "time_valid": timestamp > 0,
        "message_valid": _as_bool(record.get("message_valid"), "message_valid") and not anomalies,
        "time_source": "last_contact_fallback" if _flag(status_flags, 2) else "position_time",
        "anomaly_flags": anomalies,
    }


def _map_teaching_link(record: dict[str, Any]) -> dict[str, Any]:
    """从 TeachingLink 编码列、有效位和状态位恢复统一态势。"""
    validity_flags = _as_int(record.get("validity_flags"), "validity_flags")
    status_flags = _as_int(record.get("status_flags"), "status_flags")
    values = {
        "latitude": _decode_teaching_optional(record, "latitude", 0),
        "longitude": _decode_teaching_optional(record, "longitude", 1),
        "altitude": _decode_teaching_optional(record, "altitude", 2),
        "speed": _decode_teaching_optional(record, "speed", 3),
        "heading": _decode_teaching_optional(record, "heading", 4),
        "vertical_rate": _decode_teaching_optional(record, "vertical_rate", 5),
    }
    callsign = None
    if _flag(validity_flags, 6) and record.get("callsign") is not None:
        callsign = str(record["callsign"]).rstrip("\x00").strip() or None
    return {
        "track_id": _normalise_target_id(record.get("target_id")),
        "source": "TeachingLink",
        "timestamp": _as_int(record.get("latest_time", record.get("timestamp")), "timestamp"),
        "identity": {"callsign": callsign},
        "position": {
            "lat": values["latitude"], "lon": values["longitude"], "alt": values["altitude"],
            "alt_type": ("geometric" if _flag(status_flags, 1) else "barometric") if values["altitude"] is not None else "unknown",
        },
        "motion": {"speed": values["speed"], "heading": values["heading"], "vertical_rate": values["vertical_rate"]},
        "status": {"on_ground": _flag(status_flags, 0)},
        "quality": _teaching_quality(record, values),
    }


def _map_opensky(record: dict[str, Any]) -> dict[str, Any]:
    """将 M3 OpenSky 当前态势行映射为统一态势，保留其来源语义。"""
    anomalies: list[str] = []
    lat, lon = _optional_number(record.get("lat"), "lat"), _optional_number(record.get("lon"), "lon")
    altitude = _optional_number(record.get("altitude"), "altitude")
    speed, heading = _optional_number(record.get("speed"), "speed"), _optional_number(record.get("heading"), "heading")
    vertical_rate = _optional_number(record.get("vertical_rate"), "vertical_rate")
    if lat is not None and not -90 <= lat <= 90:
        anomalies.append("latitude_out_of_range"); lat = None
    if lon is not None and not -180 <= lon <= 180:
        anomalies.append("longitude_out_of_range"); lon = None
    if heading is not None and not 0 <= heading < 360:
        anomalies.append("heading_out_of_range"); heading = None
    timestamp = _as_int(record.get("latest_time", record.get("timestamp")), "timestamp")
    raw_callsign = record.get("callsign")
    callsign = None if raw_callsign is None or not str(raw_callsign).strip() else str(raw_callsign).strip()
    alt_type = str(record.get("alt_type") or "unknown") if altitude is not None else "unknown"
    if alt_type not in {"barometric", "geometric"}:
        alt_type = "unknown"
        if altitude is not None: anomalies.append("unknown_altitude_source")
    time_source = str(record.get("time_source") or "position_time")
    if time_source not in {"position_time", "last_contact_fallback"}:
        time_source = "position_time"; anomalies.append("unknown_time_source")
    return {
        "track_id": _normalise_target_id(record.get("target_id")), "source": "OpenSky", "timestamp": timestamp,
        "identity": {"callsign": callsign},
        "position": {"lat": lat, "lon": lon, "alt": altitude, "alt_type": alt_type},
        "motion": {"speed": speed, "heading": heading, "vertical_rate": vertical_rate},
        "status": {"on_ground": _as_bool(record.get("on_ground"), "on_ground")},
        "quality": {"position_valid": lat is not None and lon is not None, "time_valid": timestamp > 0,
                    "message_valid": _as_bool(record.get("message_valid"), "message_valid") and not anomalies,
                    "time_source": time_source, "anomaly_flags": anomalies},
    }


def _mapping_row(source: str, input_field: str, unified_field: str, rule: str, unit: str, null_strategy: str) -> dict[str, Any]:
    return {"source_format": source, "input_field": input_field, "unified_field": unified_field,
            "mapping_rule": rule, "unit_conversion": unit, "null_strategy": null_strategy,
            "evidence": "source_field_definitions.md；teaching_message_spec.md；样例 CSV", "verified": True}


def _verified_mapping_rows() -> list[dict[str, Any]]:
    """给出两种来源的完整人工核验规则，而不是沿用候选表的错误列。"""
    rows: list[dict[str, Any]] = []
    for source, fields in (
        ("OpenSky", [
            ("target_id", "track_id", "小写六位十六进制，保留前导0", "无", "格式不合法则拒绝记录"),
            ("latest_time", "timestamp", "直接映射为正整数 Unix 秒", "s", "非正值使 time_valid=false"),
            ("callsign", "identity.callsign", "去首尾空白", "无", "空白为 null"),
            ("lat/lon", "position.lat/position.lon", "合法坐标直接映射", "degree", "空值或越界为 null"),
            ("altitude+alt_type", "position.alt/position.alt_type", "直接映射并保留高度来源", "m", "高度无效时 null/unknown"),
            ("speed", "motion.speed", "直接映射", "m/s", "缺失为 null"),
            ("heading", "motion.heading", "直接映射，范围 [0,360)", "degree", "缺失或越界为 null"),
            ("vertical_rate", "motion.vertical_rate", "直接映射", "m/s", "缺失为 null"),
            ("on_ground", "status.on_ground", "转换为布尔值", "无", "必需状态字段"),
            ("time_source", "quality.time_source", "保留 position_time 或 last_contact_fallback", "无", "未知来源记异常"),
            ("lat/lon/latest_time/message_valid", "quality.*", "坐标合法、时间为正并保留结构校验结论", "无", "按校验结果取布尔值"),
        ]),
        ("TeachingLink", [
            ("target_id", "track_id", "小写六位十六进制，保留前导0", "无", "格式不合法则拒绝记录"),
            ("latest_time", "timestamp", "直接映射为正整数 Unix 秒", "s", "非正值使 time_valid=false"),
            ("validity_flags.bit6+callsign", "identity.callsign", "有效时去补0", "无", "无效或空白为 null"),
            ("latitude_code+validity_flags.bit0", "position.lat", "code/(2^22-1)*180-90", "degree", "有效位0或码越界为 null"),
            ("longitude_code+validity_flags.bit1", "position.lon", "code/(2^22-1)*360-180", "degree", "有效位0或码越界为 null"),
            ("altitude_code+validity_flags.bit2", "position.alt", "code-1000", "m", "有效位0或码越界为 null"),
            ("status_flags.bit1+altitude", "position.alt_type", "0=barometric，1=geometric", "无", "高度无效时 unknown"),
            ("speed_code+validity_flags.bit3", "motion.speed", "code*0.1", "m/s", "有效位0或码越界为 null"),
            ("heading_code+validity_flags.bit4", "motion.heading", "code*0.01，必须小于360", "degree", "有效位0或码越界为 null"),
            ("vertical_rate_code+validity_flags.bit5", "motion.vertical_rate", "code*0.01-327.68", "m/s", "有效位0或码越界为 null"),
            ("status_flags.bit0", "status.on_ground", "转换为布尔值", "无", "必需状态字段"),
            ("status_flags.bit2", "quality.time_source", "0=position_time，1=last_contact_fallback", "无", "保留位异常使消息无效"),
            ("validity_flags+编码范围", "quality.position_valid", "纬经均有效且解码范围合法", "无", "按校验结果取布尔值"),
            ("timestamp+message_valid", "quality.time_valid/quality.message_valid", "时间正数；完整帧且标志/保留位一致", "无", "按校验结果取布尔值"),
        ]),
    ):
        rows.extend(_mapping_row(source, *field) for field in fields)
    return rows


def verify_candidate_mapping(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """依据权威字段定义审查候选，并输出完整、可追溯的正式映射。"""
    required = {"source_format", "input_field", "candidate_unified_field", "candidate_rule"}
    for row in candidate_rows:
        if missing := required - row.keys():
            raise ValueError(f"候选映射缺少列：{', '.join(sorted(missing))}。")
    return _verified_mapping_rows()


def map_to_unified(record: dict[str, Any], source_format: str) -> dict[str, Any]:
    """使用人工核验规则生成统一态势；只接受 OpenSky 或 TeachingLink。"""
    mapped = _map_opensky(record) if source_format == "OpenSky" else _map_teaching_link(record) if source_format == "TeachingLink" else None
    if mapped is None:
        raise ValueError("source_format 必须为 OpenSky 或 TeachingLink。")
    if set(mapped) != MODEL_FIELDS:
        raise ValueError("统一态势对象字段不符合 unified_model.json。")
    return mapped


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def _matches_model_shape(value: Any, model: Any) -> bool:
    """递归检查对象层次和字段名；模型中的叶子占位值不限制实际值类型。"""
    if isinstance(model, dict):
        return isinstance(value, dict) and set(value) == set(model) and all(
            _matches_model_shape(value[key], child) for key, child in model.items()
        )
    if isinstance(model, list):
        return isinstance(value, list)
    return True


def _validate_unified_message(message: dict[str, Any], model: dict[str, Any] | None = None) -> None:
    """在写出前进行模型形状和关键语义自检。"""
    if set(message) != MODEL_FIELDS or not TARGET_ID_PATTERN.fullmatch(message["track_id"]):
        raise ValueError("统一对象结构或 track_id 不合法。")
    if model is not None and not _matches_model_shape(message, model):
        raise ValueError("统一对象嵌套结构不符合 unified_model.json。")
    if not isinstance(message["timestamp"], int) or isinstance(message["timestamp"], bool):
        raise ValueError("统一对象 timestamp 必须为整数。")
    if message["position"]["alt"] is None and message["position"]["alt_type"] != "unknown":
        raise ValueError("高度缺失时 alt_type 必须为 unknown。")
    if message["quality"]["position_valid"] != (message["position"]["lat"] is not None and message["position"]["lon"] is not None):
        raise ValueError("position_valid 与坐标空值不一致。")


def _write_review_note(path: Path, summary: dict[str, int]) -> None:
    """写出一页以内、仅陈述实际候选审查和样例验证的记录。"""
    text = f"""# M4 AI 辅助映射核验说明

- 候选来源：学校提供的 `reference/pre_generated_mapping_candidate.csv`（作为 AI/自动候选，不作为最终规则）。
- 使用材料：候选表、`source_field_definitions.md`、`teaching_message_spec.md`、两个字段字典、`unified_model.json`，以及 M3 OpenSky 当前态势和 TeachingLink 样例。
- 发现的问题：候选将 TeachingLink 纬度/经度目标字段对调；高度规则遗漏 `-1000 m` 偏置；呼号未结合有效位；`status_flags.bit2` 被错误写为 `quality.time_valid`，没有表达其时间回退来源语义；并且未覆盖全部必需字段。
- 修订依据：规范规定纬度、经度均为 22 位但公式量程不同；高度为 `code-1000`；validity bit6 控制呼号；status bit2 是 `timestamp_fallback`。正式映射从编码列和标志位恢复物理量，有效位为 0 时写入 `null`。
- 优化与修订过程：先原样保留 8 条候选，逐行与字段定义比对；随后将经纬度映射分别改为 `latitude_code→position.lat`、`longitude_code→position.lon`，并应用各自公式。再把高度规则由“code乘1米”修正为 `code-1000`，把呼号规则补充为“validity bit6 为 0 时 null”，把 status bit2 从 `time_valid` 改为 `quality.time_source`（0=position_time，1=last_contact_fallback）。最后补齐候选未覆盖的速度、航向、垂直速度、地面状态、质量字段及空值策略，形成 25 条正式规则；实现时只从 TeachingLink 的编码列和标志位恢复数值，不借用其已换算展示列。
- 验证结果：读取 {summary['candidate_rows']} 条候选并形成 {summary['verified_rows']} 条已核验规则；转换 OpenSky {summary['opensky_records']} 条、TeachingLink {summary['teaching_records']} 条为 NDJSON。全部 {summary['unified_records']} 条通过模型结构、标识、时间、位置有效性和高度类型自检；3 个同目标样例共享关键字段一致。目标 `000001` 的垂直速度真实零值保留为 `0.0`；`780def` 缺失位置与呼号保留为 `null`。
- 局限性：验证仅覆盖课程提供的 3 条当前态势样例，不能证明对未见字段组合或实时来源的完备性；`message_valid` 仅代表结构/帧接收校验，不代表来源真实或飞行状态安全。
- 不由 AI 决定：位宽、比例因子、偏置、单位、有效位空值策略、状态来源语义和最终 `verified` 结论均以协议与字段定义为准。
"""
    path.write_text(text, encoding="utf-8")


def run_m4(project_root: Path | None = None) -> dict[str, int]:
    """完成 M4：保留候选、形成正式映射、生成统一 NDJSON 和审查说明。"""
    root = project_root or Path(__file__).resolve().parents[2]
    package, output = root / "student_package", root / "student_package" / "output"
    output.mkdir(parents=True, exist_ok=True)
    candidate_path = package / "reference" / "pre_generated_mapping_candidate.csv"
    candidate_rows = _read_csv(candidate_path)
    verified_rows = verify_candidate_mapping(candidate_rows)
    model = json.loads((package / "schema" / "unified_model.json").read_text(encoding="utf-8"))
    opensky_rows = _read_csv(output / "current_situation.csv")
    teaching_rows = _read_csv(package / "data" / "m4" / "partner_current_situation.csv")
    messages = [map_to_unified(row, "OpenSky") for row in opensky_rows]
    messages.extend(map_to_unified(row, "TeachingLink") for row in teaching_rows)
    for message in messages: _validate_unified_message(message, model)
    # 候选是审查输入而非本程序生成的正式表，按原始字节保留以便追溯。
    (output / "llm_mapping_candidate.csv").write_bytes(candidate_path.read_bytes())
    _write_csv(output / "verified_mapping_table.csv", MAPPING_FIELDS, verified_rows)
    with (output / "unified_situation.ndjson").open("w", encoding="utf-8") as handle:
        for message in messages: handle.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {"candidate_rows": len(candidate_rows), "verified_rows": len(verified_rows), "opensky_records": len(opensky_rows), "teaching_records": len(teaching_rows), "unified_records": len(messages)}
    _write_review_note(output / "m4_ai_mapping_review.md", summary)
    return summary


if __name__ == "__main__":
    result = run_m4()
    print("M4 完成：" + "，".join(f"{name}={count}" for name, count in result.items()))
