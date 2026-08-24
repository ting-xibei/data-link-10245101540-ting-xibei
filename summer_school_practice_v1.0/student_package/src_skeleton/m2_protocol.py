from __future__ import annotations

from typing import Any


FRAME_SIZE = 41


def parse_state_vector(vector: list[Any]) -> dict[str, Any]:
    """将OpenSky状态向量转换为发送方内部结构化记录。"""
    raise NotImplementedError("M2：按字段字典实现索引、必需/可空字段、来源回退和量程检查。")


def calculate_checksum(data_without_checksum: bytes) -> int:
    """计算前39字节无符号字节值之和模65536。"""
    raise NotImplementedError("M2：实现教学校验和。")


def encode_position_message(record: dict[str, Any], message_seq: int) -> bytes:
    """按41字节TeachingLink格式封装一条位置状态消息。"""
    raise NotImplementedError("M2：实现定点量化、状态/有效性标志和大端字节封装。")


def decode_position_message(data: bytes) -> dict[str, Any]:
    """检查帧接收条件并恢复接收方结构化记录。"""
    raise NotImplementedError("M2：实现长度、头字段、校验和、保留位、标志一致性和字段恢复。")
