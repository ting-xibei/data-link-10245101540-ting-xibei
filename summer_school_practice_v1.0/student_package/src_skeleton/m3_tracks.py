from __future__ import annotations

from typing import Any


def decode_message_stream(data: bytes, frame_size: int = 41) -> list[dict[str, Any]]:
    """按固定帧长批量解码；记录并忽略不完整尾帧。"""
    raise NotImplementedError("M3：调用本人M2解码函数，并保留每帧验证结果。")


def save_records_to_sqlite(records: list[dict[str, Any]], db_path: str) -> None:
    """选做：保存接收记录，None必须写为NULL。"""
    raise NotImplementedError("M3选做：按optional_db_schema.sql实现写入、读取和简单查询。")


def build_tracks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅使用可接受记录，按target_id分组并按timestamp排序。"""
    raise NotImplementedError("M3：生成从1开始的track_sequence_no。")


def build_current_situation(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每个目标保留时间最新的可接受记录；可选字段缺失仍可入选。"""
    raise NotImplementedError("M3：生成current_situation.csv所需字段。")
