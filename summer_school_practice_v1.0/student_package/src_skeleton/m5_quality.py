"""M5：使用固定规则生成告警日志和每条记录的质量状态。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


# 固定批次时间使延迟判断和实验输出可以重复验证。
BATCH_TIME = 1710000120
ALERT_FIELDS = ["alert_time", "target_id", "alert_type", "severity", "field", "description"]
QUALITY_FIELDS = [
    "target_id",
    "timestamp",
    "position_valid",
    "delayed",
    "duplicate_detected",
    "heading_valid",
    "message_valid",
    "anomaly_level",
    "display_status",
]
RULE_REQUIREMENTS = {
    "R1": ("POSITION_MISSING", "HIGH"),
    "R2": ("DATA_DELAYED", "MEDIUM"),
    "R3": ("DUPLICATE_RECORD", "MEDIUM"),
    "R4": ("HEADING_OUT_OF_RANGE", "MEDIUM"),
}


def _is_missing(value: Any) -> bool:
    """空值才表示缺失；真实的数值 0 仍是有效物理量。"""
    return value is None or (isinstance(value, str) and not value.strip())


def _as_int(value: Any, field: str) -> int:
    """将输入转换为整数，避免布尔值或空文本混入时间字段。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能为布尔值。")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{field} 必须为整数。")


def _as_number(value: Any, field: str) -> float | None:
    """将数值字段转换为浮点数；空值保留为 None。"""
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能为布尔值。")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} 必须为数值或空值。") from error


def _as_bool(value: Any, field: str) -> bool:
    """读取布尔字段，兼容 CSV 中的 True/False 文本。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{field} 必须为布尔值。")


def _record_time(record: dict[str, Any]) -> int:
    """优先取最新态势时间，没有时回退到记录时间。"""
    """延迟检查只使用已传输的 latest_time 或 timestamp。"""
    candidate = record.get("latest_time")
    if _is_missing(candidate):
        candidate = record.get("timestamp")
    return _as_int(candidate, "latest_time/timestamp")


def _timestamp(record: dict[str, Any]) -> int:
    """取得用于重复记录分组的时间戳。"""
    """重复联合键和质量输出使用记录的 timestamp。"""
    return _as_int(record.get("timestamp"), "timestamp")


def _alert(
    record: dict[str, Any],
    alert_type: str,
    severity: str,
    field: str,
    description: str,
    alert_time: int = BATCH_TIME,
) -> dict[str, Any]:
    """只构造手册规定的告警日志列，不向公共结果暴露内部关联字段。"""
    return {
        "alert_time": alert_time,
        "target_id": str(record.get("target_id", "")),
        "alert_type": alert_type,
        "severity": severity,
        "field": field,
        "description": description,
    }


def _has_frame_validation_error(record: dict[str, Any]) -> bool:
    """选做帧异常的唯一判据：接收失败或上游明确提供校验错误。"""
    return not _as_bool(record.get("message_valid"), "message_valid") or not _is_missing(record.get("validation_errors"))


def check_record(record: dict[str, Any], batch_time: int = BATCH_TIME) -> list[dict[str, Any]]:
    """检查 R1、R2、R4，以及选做的帧接收异常。"""
    alerts: list[dict[str, Any]] = []
    missing_position = [field for field in ("lat", "lon") if _is_missing(record.get(field))]
    if missing_position:
        alerts.append(
            _alert(
                record,
                "POSITION_MISSING",
                "HIGH",
                "/".join(missing_position),
                f"位置字段缺失：{', '.join(missing_position)}。",
                batch_time,
            )
        )

    record_time = _record_time(record)
    delay_seconds = batch_time - record_time
    if delay_seconds > 60:
        alerts.append(
            _alert(
                record,
                "DATA_DELAYED",
                "MEDIUM",
                "latest_time/timestamp",
                f"批次时间 {batch_time} 与记录时间 {record_time} 相差 {delay_seconds} 秒，超过 60 秒。",
                batch_time,
            )
        )

    heading = _as_number(record.get("heading"), "heading")
    if heading is not None and not 0 <= heading < 360:
        alerts.append(
            _alert(
                record,
                "HEADING_OUT_OF_RANGE",
                "MEDIUM",
                "heading",
                f"航向 {heading} 不在 [0, 360) 度范围内。",
                batch_time,
            )
        )

    # 选做：仅在帧接收结论为失败或上游明确携带校验错误时报告，
    # 不能把位置等可选字段的缺失误报为帧异常。
    validation_errors = record.get("validation_errors")
    if _has_frame_validation_error(record):
        detail = str(validation_errors).strip() if not _is_missing(validation_errors) else "message_valid=false"
        alerts.append(
            _alert(
                record,
                "FRAME_VALIDATION_ERROR",
                "HIGH",
                "message_valid/validation_errors",
                f"帧未通过接收检查：{detail}。",
                batch_time,
            )
        )
    return alerts


def check_duplicates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 target_id+timestamp 联合键分组，为重复组中的每条记录告警。"""
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        key = (str(record.get("target_id", "")), _timestamp(record))
        grouped.setdefault(key, []).append(record)

    alerts: list[dict[str, Any]] = []
    for (target_id, timestamp), duplicates in grouped.items():
        if len(duplicates) > 1:
            for record in duplicates:
                alerts.append(
                    _alert(
                        record,
                        "DUPLICATE_RECORD",
                        "MEDIUM",
                        "target_id+timestamp",
                        f"联合键 ({target_id}, {timestamp}) 出现 {len(duplicates)} 次。",
                    )
                )
    return alerts


def build_quality_situation(records: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 HIGH > MEDIUM > NONE 合成每条输入记录的质量态势。

    alert_log 的模板没有记录时间列，不能安全地仅凭 target_id 把告警反向关联到
    某条记录；因此此处按与告警生成相同的固定规则直接计算每条记录的状态。
    """
    if not isinstance(alerts, list):
        raise TypeError("alerts 必须是告警列表。")
    duplicate_keys: set[tuple[str, int]] = set()
    counts: dict[tuple[str, int], int] = {}
    for record in records:
        key = (str(record.get("target_id", "")), _timestamp(record))
        counts[key] = counts.get(key, 0) + 1
    duplicate_keys = {key for key, count in counts.items() if count > 1}
    quality_rows: list[dict[str, Any]] = []
    for record in records:
        timestamp = _timestamp(record)
        key = (str(record.get("target_id", "")), timestamp)
        position_missing = _is_missing(record.get("lat")) or _is_missing(record.get("lon"))
        delayed = BATCH_TIME - _record_time(record) > 60
        heading = _as_number(record.get("heading"), "heading")
        heading_invalid = heading is not None and not 0 <= heading < 360
        frame_invalid = _has_frame_validation_error(record)
        duplicate_detected = key in duplicate_keys
        anomaly_level = "HIGH" if position_missing or frame_invalid else "MEDIUM" if delayed or duplicate_detected or heading_invalid else "NONE"
        display_status = "ERROR" if anomaly_level == "HIGH" else "WARNING" if anomaly_level == "MEDIUM" else "NORMAL"
        quality_rows.append(
            {
                "target_id": key[0],
                "timestamp": timestamp,
                "position_valid": not position_missing,
                "delayed": delayed,
                "duplicate_detected": duplicate_detected,
                "heading_valid": not heading_invalid,
                "message_valid": _as_bool(record.get("message_valid"), "message_valid"),
                "anomaly_level": anomaly_level,
                "display_status": display_status,
            }
        )
    return quality_rows


def _read_cases(path: Path) -> list[dict[str, Any]]:
    """读取 M5 样例；字段空白保持为 None，避免把真实 0 当作缺失。"""
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            records.append(
                {
                    "target_id": row["target_id"],
                    "timestamp": _as_int(row["timestamp"], "timestamp"),
                    "lat": _as_number(row["lat"], "lat"),
                    "lon": _as_number(row["lon"], "lon"),
                    "heading": _as_number(row["heading"], "heading"),
                    "message_valid": _as_bool(row["message_valid"], "message_valid"),
                }
            )
    return records


def _validate_rule_file(path: Path) -> None:
    """确认输入规则文件仍是手册规定的四条固定规则。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actual = {row["rule_id"]: (row["alert_type"], row["severity"]) for row in rows}
    if actual != RULE_REQUIREMENTS:
        raise ValueError("anomaly_rules.csv 不符合 M5 手册规定的 R1-R4 固定规则。")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    """按课程模板写出告警或质量态势 CSV。"""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_m5(project_root: Path | None = None) -> dict[str, int]:
    """执行 M5 四条必做规则，写出告警日志和质量增强态势。"""
    root = project_root or Path(__file__).resolve().parents[2]
    package = root / "student_package"
    output = package / "output"
    output.mkdir(parents=True, exist_ok=True)
    _validate_rule_file(package / "data" / "m5" / "anomaly_rules.csv")
    records = _read_cases(package / "data" / "m5" / "anomaly_cases.csv")
    alerts = [alert for record in records for alert in check_record(record)]
    alerts.extend(check_duplicates(records))
    quality_rows = build_quality_situation(records, alerts)
    _write_csv(output / "alert_log.csv", ALERT_FIELDS, alerts)
    _write_csv(output / "quality_situation.csv", QUALITY_FIELDS, quality_rows)
    return {"input_records": len(records), "alerts": len(alerts), "quality_rows": len(quality_rows)}


if __name__ == "__main__":
    result = run_m5()
    print("M5 完成：" + "，".join(f"{name}={count}" for name, count in result.items()))
