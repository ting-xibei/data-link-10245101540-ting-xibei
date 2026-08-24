from __future__ import annotations

from typing import Any


def verify_candidate_mapping(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """依据字段定义、单位、有效性和样例，形成人工核验后的正式映射。"""
    raise NotImplementedError("M4：不要直接照抄预生成候选；填写证据与verified。")


def map_to_unified(record: dict[str, Any], source_format: str) -> dict[str, Any]:
    """使用人工核验后的规则生成统一态势消息。"""
    raise NotImplementedError("M4：恢复比例因子/偏置、空值、alt_type、time_source和质量字段。")
