from __future__ import annotations

from typing import Any


BATCH_TIME = 1710000120


def check_record(record: dict[str, Any], batch_time: int = BATCH_TIME) -> list[dict[str, Any]]:
    """检查位置缺失、时间延迟和航向越界。"""
    raise NotImplementedError("M5：按anomaly_rules.csv实现固定规则。")


def check_duplicates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """使用target_id+timestamp联合键检查重复。"""
    raise NotImplementedError("M5：不要只按target_id判断重复。")


def build_quality_situation(records: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按HIGH > MEDIUM > NONE合成质量态势。"""
    raise NotImplementedError("M5：生成quality_situation.csv。")
