"""M5：一致性保障。

本模块读取课程提供的异常样例，依次执行四条固定规则：

R1 位置缺失、R2 数据延迟、R3 重复记录、R4 航向越界。

程序最终生成两个文件：

* alert_log.csv：一条异常对应一条告警，便于排错和审计；
* quality_situation.csv：一条输入记录对应一条综合质量状态，便于上层显示。

注意：M5 检查的是数据质量，并不负责判断飞机身份是否真实、飞行是否安全。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


# batch_time 是“本批数据开始检查时的统一参考时间”，不是某架飞机的观测时间。
# 课程将其固定下来，使不同学生、不同日期运行时都能得到相同的延迟判断结果。
BATCH_TIME = 1710000120

# 两个输出文件的列顺序由实验手册规定。集中定义可避免写 CSV 时漏列或乱序。
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
# anomaly_rules.csv 必须恰好包含以下四条必做规则。
# 运行前会核对规则编号、告警类型和等级，防止规则文件被误改后悄悄产生错误结果。
RULE_REQUIREMENTS = {
    "R1": ("POSITION_MISSING", "HIGH"),
    "R2": ("DATA_DELAYED", "MEDIUM"),
    "R3": ("DUPLICATE_RECORD", "MEDIUM"),
    "R4": ("HEADING_OUT_OF_RANGE", "MEDIUM"),
}


def _is_missing(value: Any) -> bool:
    """判断字段是否真正缺失。

    ``None``、空字符串和只含空格的字符串算缺失；数值 0 不算缺失。
    这一点很重要，因为经纬度、航向等字段的 0 都可能是真实物理值。
    """
    return value is None or (isinstance(value, str) and not value.strip())


def _as_int(value: Any, field: str) -> int:
    """将 CSV 中的时间等字段严格转换成整数。

    Python 中 ``bool`` 是 ``int`` 的子类，但 True/False 显然不能作为时间戳，
    所以这里先单独拒绝布尔值。非法输入立即报错，避免后面的规则静默误判。
    """
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能为布尔值。")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{field} 必须为整数。")


def _as_number(value: Any, field: str) -> float | None:
    """将经纬度、航向等字段转换为浮点数，空值则保留为 ``None``。

    保留 ``None`` 是为了让 R1/R4 能区分“字段缺失”和“数值等于 0”。
    """
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能为布尔值。")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} 必须为数值或空值。") from error


def _as_bool(value: Any, field: str) -> bool:
    """读取布尔字段，兼容 Python 布尔值和 CSV 中的 True/False 文本。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{field} 必须为布尔值。")


def _record_time(record: dict[str, Any]) -> int:
    """取得 R2 延迟检查使用的记录时间。

    M3 生成的当前态势通常使用 ``latest_time`` 表示该目标最新状态的时间；
    原始或普通状态记录通常只有 ``timestamp``。因此这里优先使用
    ``latest_time``，缺失时回退到 ``timestamp``。不能改用未传输的
    ``last_contact``，否则不同处理阶段会得到不一致的延迟结论。
    """
    candidate = record.get("latest_time")
    if _is_missing(candidate):
        candidate = record.get("timestamp")
    return _as_int(candidate, "latest_time/timestamp")


def _timestamp(record: dict[str, Any]) -> int:
    """取得记录自身的时间戳。

    R3 使用 ``target_id + timestamp`` 作为联合键；质量输出的 timestamp 列
    也使用这个值。它与 R2 可能采用的 latest_time 不应混为一谈。
    """
    return _as_int(record.get("timestamp"), "timestamp")


def _alert(
    record: dict[str, Any],
    alert_type: str,
    severity: str,
    field: str,
    description: str,
    alert_time: int = BATCH_TIME,
) -> dict[str, Any]:
    """按手册规定的六列构造一条告警。

    统一在这里组装告警，可以保证 R1-R4 的输出格式完全一致。
    ``alert_time`` 表示发现异常的批次时间，而不是异常记录的观测时间。
    """
    return {
        "alert_time": alert_time,
        "target_id": str(record.get("target_id", "")),
        "alert_type": alert_type,
        "severity": severity,
        "field": field,
        "description": description,
    }


def _has_frame_validation_error(record: dict[str, Any]) -> bool:
    """判断是否触发选做的 FRAME_VALIDATION_ERROR。

    接收结论 ``message_valid=false``，或上游明确给出专用的
    ``frame_validation_errors``，才算帧验证失败。通用 ``validation_errors``
    可能包含可选字段级诊断，不能据此把整个 TeachingLink 帧判为无效。
    """
    return not _as_bool(record.get("message_valid"), "message_valid") or not _is_missing(record.get("frame_validation_errors"))


def check_record(record: dict[str, Any], batch_time: int = BATCH_TIME) -> list[dict[str, Any]]:
    """对一条记录执行 R1、R2、R4，以及选做的帧接收异常检查。

    R3 必须比较全部记录，所以不在本函数处理，而由 ``check_duplicates``
    统一分组检查。一条记录可以同时产生多条告警，不能命中一条后就提前返回。
    """
    alerts: list[dict[str, Any]] = []

    # R1：纬度或经度任意一个缺失，位置就不完整。
    # 用列表保留具体缺失字段，便于告警日志指出是 lat、lon 还是两者都缺失。
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

    # R2：数据年龄 = 统一批次时间 - 记录时间。
    # 手册规定严格“大于 60 秒”才告警，因此恰好 60 秒仍然正常。
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

    # R4：合法航向范围是左闭右开区间 [0, 360)。
    # 空航向不触发 R4；360 度越界，不能静默取模成 0 度。
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
    validation_errors = record.get("frame_validation_errors")
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
    """执行 R3：按 ``target_id + timestamp`` 联合键检查重复。

    ``target_id`` 相同而 timestamp 不同，表示同一目标在不同时刻的正常状态；
    timestamp 相同而 target_id 不同，表示不同目标恰好同时上报。只有两者同时
    相同，才满足本实验对重复记录的定义。

    课程规则要求重复组里的每条记录都标记，因此一组两条副本会产生两条告警。
    """
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        # tuple 作为字典键，代表一条目标状态的逻辑身份。
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
    # alerts 参数代表前一步的告警结果；先校验接口类型，防止调用方误传其他对象。
    if not isinstance(alerts, list):
        raise TypeError("alerts 必须是告警列表。")

    # 先统计每个联合键出现的次数，出现两次及以上的键都属于重复组。
    duplicate_keys: set[tuple[str, int]] = set()
    counts: dict[tuple[str, int], int] = {}
    for record in records:
        key = (str(record.get("target_id", "")), _timestamp(record))
        counts[key] = counts.get(key, 0) + 1
    duplicate_keys = {key for key, count in counts.items() if count > 1}
    quality_rows: list[dict[str, Any]] = []
    for record in records:
        # 对每条输入记录重新计算各个布尔质量标志。
        # 这样即使同一 target_id 有多个不同时刻的状态，也不会把告警错误地串行。
        timestamp = _timestamp(record)
        key = (str(record.get("target_id", "")), timestamp)
        position_missing = _is_missing(record.get("lat")) or _is_missing(record.get("lon"))
        delayed = BATCH_TIME - _record_time(record) > 60
        heading = _as_number(record.get("heading"), "heading")
        heading_valid = heading is not None and 0 <= heading < 360
        heading_invalid = heading is not None and not heading_valid
        frame_invalid = _has_frame_validation_error(record)
        duplicate_detected = key in duplicate_keys
        # 综合等级遵循 HIGH > MEDIUM > NONE。位置缺失和帧无效是 HIGH；
        # 延迟、重复、航向越界是 MEDIUM。多种异常同时存在时取最高等级。
        anomaly_level = "HIGH" if position_missing or frame_invalid else "MEDIUM" if delayed or duplicate_detected or heading_invalid else "NONE"

        # display_status 是面向上层界面的简化状态，分别对应红色错误、黄色警告和正常。
        display_status = "ERROR" if anomaly_level == "HIGH" else "WARNING" if anomaly_level == "MEDIUM" else "NORMAL"
        quality_rows.append(
            {
                "target_id": key[0],
                "timestamp": timestamp,
                "position_valid": not position_missing,
                "delayed": delayed,
                "duplicate_detected": duplicate_detected,
                "heading_valid": heading_valid,
                "message_valid": _as_bool(record.get("message_valid"), "message_valid"),
                "anomaly_level": anomaly_level,
                "display_status": display_status,
            }
        )
    return quality_rows


def _read_cases(path: Path) -> list[dict[str, Any]]:
    """读取 M5 样例并完成必要的类型转换。

    ``utf-8-sig`` 同时兼容普通 UTF-8 和带 BOM 的 CSV；``newline=''`` 是
    Python csv 模块推荐的打开方式。字段空白会保留为 None，真实数值 0 不受影响。
    """
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
    """确认规则文件仍然是实验手册规定的四条固定规则。

    这里比较的是规则编号、告警类型和严重等级；具体判断逻辑由本模块实现。
    如果规则缺失、多出或被改名，程序直接停止，避免输出看似正常但口径错误。
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actual = {row["rule_id"]: (row["alert_type"], row["severity"]) for row in rows}
    if actual != RULE_REQUIREMENTS:
        raise ValueError("anomaly_rules.csv 不符合 M5 手册规定的 R1-R4 固定规则。")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    """按照课程模板指定的列写出 CSV。

    使用 UTF-8 BOM，方便 Windows Excel 正确识别中文；``extrasaction='ignore'``
    只允许模板要求的字段进入最终成果，内部辅助数据不会意外泄漏到输出列。
    """
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_m5(project_root: Path | None = None) -> dict[str, int]:
    """执行完整 M5 流程，并返回便于核对的数量摘要。

    执行顺序是：定位目录 → 校验规则 → 读取样例 → 逐条检查 → 重复检查
    → 合成质量状态 → 写出两个 CSV。默认从本文件位置推导项目根目录，测试时
    也可以显式传入 ``project_root``。
    """
    root = project_root or Path(__file__).resolve().parents[2]
    package = root / "student_package"
    output = package / "output"
    output.mkdir(parents=True, exist_ok=True)

    # 先验证规则再读取和处理数据：规则口径不正确时，不应生成任何新成果。
    _validate_rule_file(package / "data" / "m5" / "anomaly_rules.csv")
    records = _read_cases(package / "data" / "m5" / "anomaly_cases.csv")

    # R1/R2/R4 是单记录规则，可逐条执行；R3 需要看到全体记录，随后追加。
    alerts = [alert for record in records for alert in check_record(record)]
    alerts.extend(check_duplicates(records))

    # 告警日志保留每个异常的细节，质量态势则把每条输入压缩为一个最高等级状态。
    quality_rows = build_quality_situation(records, alerts)
    _write_csv(output / "alert_log.csv", ALERT_FIELDS, alerts)
    _write_csv(output / "quality_situation.csv", QUALITY_FIELDS, quality_rows)

    # 数量摘要既方便人在终端检查，也方便后续集成程序判断处理规模是否符合预期。
    return {"input_records": len(records), "alerts": len(alerts), "quality_rows": len(quality_rows)}


if __name__ == "__main__":
    # 只有直接运行本文件时才执行实验；被其他模块导入时不会自动改写输出文件。
    result = run_m5()
    print("M5 完成：" + "，".join(f"{name}={count}" for name, count in result.items()))
