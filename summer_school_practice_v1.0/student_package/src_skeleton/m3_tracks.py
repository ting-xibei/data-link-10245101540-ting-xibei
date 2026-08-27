"""M3：将多时刻 TeachingLink 消息组织为航迹、当前态势和可选 SQLite 数据。"""

from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from m2_protocol import (
    DECODED_FIELDS,
    FRAME_SIZE,
    ROUNDTRIP_FIELDS,
    ProtocolError,
    _roundtrip_rows,
    decode_position_message,
    encode_position_message,
    parse_state_vector,
)


# 航迹表保存同一目标按时间排序后的全部历史点。
TRACK_FIELDS = [
    "target_id",
    "timestamp",
    "message_seq",
    "track_sequence_no",
    "lat",
    "lon",
    "altitude",
    "speed",
    "heading",
]
# 当前态势表只保留每个目标时间最新的一条可接受记录。
CURRENT_SITUATION_FIELDS = [
    "target_id",
    "callsign",
    "latest_time",
    "lat",
    "lon",
    "altitude",
    "speed",
    "heading",
    "vertical_rate",
    "on_ground",
    "track_length",
    "alt_type",
    "time_source",
    "message_valid",
]
SQLITE_FIELDS = [
    "target_id",
    "callsign",
    "timestamp",
    "timestamp_source",
    "message_seq",
    "lat",
    "lon",
    "altitude",
    "alt_type",
    "speed",
    "heading",
    "vertical_rate",
    "on_ground",
    "status_flags",
    "validity_flags",
    "message_valid",
    "source",
]
SQLITE_QUERY_FIELDS = ["target_id", "timestamp", "callsign", "lat", "lon", "altitude", "speed", "heading"]
REAL_SOURCE_FIELDS = [
    "record_no",
    "snapshot_index",
    "snapshot_time",
    "source_vector_index",
    "target_id",
    "callsign",
    "timestamp",
    "timestamp_source",
    "lat",
    "lon",
    "altitude",
    "alt_type",
    "speed",
    "heading",
    "vertical_rate",
    "on_ground",
]
REAL_DECODED_FIELDS = ["record_no", "snapshot_index", "source_vector_index"] + DECODED_FIELDS
REAL_TRANSMISSION_FIELDS = [
    "record_no",
    "snapshot_index",
    "source_vector_index",
    "target_id",
    "message_seq",
    "frame_length",
    "checksum",
    "message_valid",
    "validation_errors",
]
REAL_PRECISION_FIELDS = ["record_no", "snapshot_index", "source_vector_index"] + ROUNDTRIP_FIELDS
SQLITE_SCHEMA = """
CREATE TABLE state_record (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT,
    callsign TEXT NULL,
    timestamp INTEGER,
    timestamp_source TEXT,
    message_seq INTEGER,
    lat REAL NULL,
    lon REAL NULL,
    altitude REAL NULL,
    alt_type TEXT NULL,
    speed REAL NULL,
    heading REAL NULL,
    vertical_rate REAL NULL,
    on_ground INTEGER,
    status_flags INTEGER,
    validity_flags INTEGER,
    message_valid INTEGER,
    source TEXT
);
"""


def decode_message_stream(data: bytes, frame_size: int = FRAME_SIZE) -> list[dict[str, Any]]:
    """按固定帧长批量解码；记录并忽略不完整尾帧。"""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("M3 输入必须是 bytes 或 bytearray。")
    if frame_size != FRAME_SIZE:
        raise ValueError(f"M3 固定帧长必须为 {FRAME_SIZE} 字节。")

    raw = bytes(data)
    complete_count, remainder = divmod(len(raw), frame_size)
    records: list[dict[str, Any]] = []
    for frame_index in range(complete_count):
        start = frame_index * frame_size
        record = dict(decode_position_message(raw[start : start + frame_size]))
        record["frame_index"] = frame_index + 1
        records.append(record)

    if remainder:
        records.append(
            {
                "frame_index": complete_count + 1,
                "message_valid": False,
                "validation_errors": "frame:LENGTH_ERROR",
                "source": "TeachingLink",
            }
        )
    return records


def save_records_to_sqlite(records: list[dict[str, Any]], db_path: str) -> None:
    """选做：保存接收记录，None必须写为NULL。"""
    acceptable = [record for record in records if _is_acceptable(record)]
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("DROP TABLE IF EXISTS state_record")
        connection.executescript(SQLITE_SCHEMA)
        connection.executemany(
            """
            INSERT INTO state_record (
                target_id, callsign, timestamp, timestamp_source, message_seq,
                lat, lon, altitude, alt_type, speed, heading, vertical_rate,
                on_ground, status_flags, validity_flags, message_valid, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.get("target_id"),
                    record.get("callsign"),
                    record.get("timestamp"),
                    record.get("timestamp_source", record.get("time_source")),
                    record.get("message_seq"),
                    record.get("lat"),
                    record.get("lon"),
                    record.get("altitude"),
                    record.get("alt_type"),
                    record.get("speed"),
                    record.get("heading"),
                    record.get("vertical_rate"),
                    int(record.get("on_ground", False)),
                    record.get("status_flags"),
                    record.get("validity_flags"),
                    int(record.get("message_valid", False)),
                    record.get("source"),
                )
                for record in acceptable
            ],
        )
        connection.commit()
    finally:
        connection.close()


def read_records_from_sqlite(db_path: str) -> list[dict[str, Any]]:
    """选做：从 SQLite 重读接收记录，用于验证 NULL 与关键字段。"""
    columns = ", ".join(SQLITE_FIELDS)
    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(f"SELECT {columns} FROM state_record ORDER BY target_id, timestamp").fetchall()
    finally:
        connection.close()
    records = [dict(row) for row in rows]
    for record in records:
        record["on_ground"] = bool(record["on_ground"])
        record["message_valid"] = bool(record["message_valid"])
    return records


def query_records_by_target(db_path: str, target_id: str) -> list[dict[str, Any]]:
    """选做：按 target_id 查询一条航迹的时间序列。"""
    columns = ", ".join(SQLITE_QUERY_FIELDS)
    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT {columns} FROM state_record WHERE target_id = ? ORDER BY timestamp",
            (target_id,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _is_acceptable(record: dict[str, Any]) -> bool:
    """M3 航迹的准入条件：帧有效、目标标识和时间可用。"""
    return (
        record.get("message_valid") is True
        and isinstance(record.get("target_id"), str)
        and record.get("target_id") != ""
        and isinstance(record.get("timestamp"), int)
        and not isinstance(record.get("timestamp"), bool)
    )


def build_tracks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅使用可接受记录，按target_id分组并按timestamp排序。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if _is_acceptable(record):
            grouped.setdefault(record["target_id"], []).append(record)

    tracks: list[dict[str, Any]] = []
    for target_id in sorted(grouped):
        for sequence_no, record in enumerate(sorted(grouped[target_id], key=lambda item: item["timestamp"]), start=1):
            tracks.append(
                {
                    "target_id": target_id,
                    "timestamp": record["timestamp"],
                    "message_seq": record.get("message_seq"),
                    "track_sequence_no": sequence_no,
                    "lat": record.get("lat"),
                    "lon": record.get("lon"),
                    "altitude": record.get("altitude"),
                    "speed": record.get("speed"),
                    "heading": record.get("heading"),
                }
            )
    return tracks


def build_current_situation(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每个目标保留时间最新的可接受记录；可选字段缺失仍可入选。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if _is_acceptable(record):
            grouped.setdefault(record["target_id"], []).append(record)

    situation: list[dict[str, Any]] = []
    for target_id in sorted(grouped):
        track = sorted(grouped[target_id], key=lambda item: item["timestamp"])
        latest = track[-1]
        situation.append(
            {
                "target_id": target_id,
                "callsign": latest.get("callsign"),
                "latest_time": latest["timestamp"],
                "lat": latest.get("lat"),
                "lon": latest.get("lon"),
                "altitude": latest.get("altitude"),
                "speed": latest.get("speed"),
                "heading": latest.get("heading"),
                "vertical_rate": latest.get("vertical_rate"),
                "on_ground": latest.get("on_ground"),
                "track_length": len(track),
                "alt_type": latest.get("alt_type"),
                "time_source": latest.get("time_source", latest.get("timestamp_source")),
                "message_valid": latest["message_valid"],
            }
        )
    return situation


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    """按模板字段顺序写出 M3 CSV 成果。"""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _verify_sqlite_roundtrip(records: list[dict[str, Any]], reloaded: list[dict[str, Any]]) -> None:
    """选做自检：确认可接受记录数量和 None/关键字段在 SQLite 往返后一致。"""
    source = sorted((record for record in records if _is_acceptable(record)), key=lambda item: (item["target_id"], item["timestamp"]))
    if len(source) != len(reloaded):
        raise ValueError("SQLite 写入/重读记录数不一致。")
    for original, restored in zip(source, reloaded):
        for field in SQLITE_FIELDS:
            expected = original.get(field)
            if field == "timestamp_source":
                expected = original.get("timestamp_source", original.get("time_source"))
            if field in {"on_ground", "message_valid"}:
                expected = bool(expected)
            if restored.get(field) != expected:
                raise ValueError(f"SQLite 往返字段不一致：{field}。")


def plot_trajectories(records: list[dict[str, Any]], output_path: str) -> None:
    """选做：按目标绘制经纬度航迹；位置缺失记录保留为文字说明而不伪造坐标。"""
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "m3_matplotlib_cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if _is_acceptable(record):
            grouped.setdefault(record["target_id"], []).append(record)

    targets = sorted(grouped)
    figure, axes = plt.subplots(1, len(targets), figsize=(5.4 * len(targets), 4.8), squeeze=False)
    for axis, target_id in zip(axes[0], targets):
        track = sorted(grouped[target_id], key=lambda item: item["timestamp"])
        positioned = [record for record in track if record.get("lat") is not None and record.get("lon") is not None]
        missing_position = len(track) - len(positioned)
        if positioned:
            lons = [float(record["lon"]) for record in positioned]
            lats = [float(record["lat"]) for record in positioned]
            axis.plot(lons, lats, color="#2878B5", linewidth=1.8, zorder=1)
            axis.scatter(lons, lats, color="#2878B5", s=42, zorder=2, label="Track point")
            axis.scatter(lons[0], lats[0], color="#36A269", s=75, marker="o", zorder=3, label="Start")
            axis.scatter(lons[-1], lats[-1], color="#E48B18", s=120, marker="*", zorder=4, label="Latest positioned point")
            for sequence_no, record in enumerate(positioned, start=1):
                axis.annotate(
                    str(sequence_no),
                    (float(record["lon"]), float(record["lat"])),
                    xytext=(5, 5),
                    textcoords="offset points",
                    fontsize=9,
                )
            mean_latitude = sum(lats) / len(lats)
            axis.set_aspect(1 / max(math.cos(math.radians(mean_latitude)), 0.01))
            axis.ticklabel_format(style="plain", useOffset=False, axis="both")
        else:
            axis.text(0.5, 0.5, "No plottable coordinates", ha="center", va="center", transform=axis.transAxes)
        missing_note = f"\n{missing_position} valid record(s) lack position" if missing_position else ""
        axis.set_title(f"Target {target_id} (track points: {len(track)}){missing_note}")
        axis.set_xlabel("Longitude (°)")
        axis.set_ylabel("Latitude (°)")
        axis.grid(True, alpha=0.28)
        axis.legend(loc="best", fontsize=8)
    figure.suptitle("M3 Longitude-Latitude Trajectories (timestamp ascending)", fontsize=14)
    figure.tight_layout()
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _load_real_opensky_vectors(source_directory: Path) -> list[dict[str, Any]]:
    """读取冻结的 OpenSky 原始快照，保留快照和向量序号以便追溯。"""
    loaded: list[dict[str, Any]] = []
    for snapshot_index, path in enumerate(sorted(source_directory.glob("*.json")), start=1):
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshot_time = payload.get("time")
        states = payload.get("states", [])
        if not isinstance(states, list):
            raise ValueError(f"真实快照 {path.name} 缺少 states 数组。")
        for source_vector_index, vector in enumerate(states, start=1):
            loaded.append(
                {
                    "snapshot_index": snapshot_index,
                    "snapshot_time": snapshot_time,
                    "source_vector_index": source_vector_index,
                    "vector": vector,
                }
            )
    return loaded


def run_real_opensky_validation(project_root: Path | None = None) -> dict[str, int]:
    """执行手册 6.6：真实快照的 M2 编解码、M3 航迹、SQLite 与精度验证。"""
    root = project_root or Path(__file__).resolve().parents[2]
    package = root / "student_package"
    source_directory = package / "data" / "opensky_real" / "source"
    output = package / "output"
    output.mkdir(parents=True, exist_ok=True)

    source_rows: list[dict[str, Any]] = []
    decoded_rows: list[dict[str, Any]] = []
    transmission_rows: list[dict[str, Any]] = []
    precision_rows: list[dict[str, Any]] = []
    decoded_records: list[dict[str, Any]] = []
    frames: list[bytes] = []
    parse_errors = 0
    sequence = 1

    for record_no, item in enumerate(_load_real_opensky_vectors(source_directory), start=1):
        target_hint = item["vector"][0] if isinstance(item["vector"], list) and item["vector"] else ""
        try:
            source_record = parse_state_vector(item["vector"])
            frame = encode_position_message(source_record, sequence)
            decoded = decode_position_message(frame)
        except ProtocolError as error:
            parse_errors += 1
            transmission_rows.append(
                {
                    "record_no": record_no,
                    "snapshot_index": item["snapshot_index"],
                    "source_vector_index": item["source_vector_index"],
                    "target_id": target_hint,
                    "message_seq": "",
                    "frame_length": 0,
                    "checksum": "",
                    "message_valid": False,
                    "validation_errors": f"{error.field}:{error.problem_type}",
                }
            )
            continue

        source_rows.append(
            {
                "record_no": record_no,
                "snapshot_index": item["snapshot_index"],
                "snapshot_time": item["snapshot_time"],
                "source_vector_index": item["source_vector_index"],
                **source_record,
            }
        )
        frames.append(frame)
        decoded_records.append(decoded)
        decoded_rows.append(
            {
                "record_no": record_no,
                "snapshot_index": item["snapshot_index"],
                "source_vector_index": item["source_vector_index"],
                **decoded,
            }
        )
        transmission_rows.append(
            {
                "record_no": record_no,
                "snapshot_index": item["snapshot_index"],
                "source_vector_index": item["source_vector_index"],
                "target_id": decoded.get("target_id"),
                "message_seq": decoded.get("message_seq"),
                "frame_length": len(frame),
                "checksum": decoded.get("checksum"),
                "message_valid": decoded.get("message_valid"),
                "validation_errors": decoded.get("validation_errors"),
            }
        )
        for row in _roundtrip_rows(source_record, decoded):
            precision_rows.append(
                {
                    "record_no": record_no,
                    "snapshot_index": item["snapshot_index"],
                    "source_vector_index": item["source_vector_index"],
                    **row,
                }
            )
        sequence += 1

    _write_csv(output / "receiver_situation_initial.csv", CURRENT_SITUATION_FIELDS, [])
    _write_csv(output / "selected_source_states.csv", REAL_SOURCE_FIELDS, source_rows)
    (output / "transmitted_frames.bin").write_bytes(b"".join(frames))
    _write_csv(output / "transmission_log.csv", REAL_TRANSMISSION_FIELDS, transmission_rows)
    _write_csv(output / "decoded_states.csv", REAL_DECODED_FIELDS, decoded_rows)
    final_situation = build_current_situation(decoded_records)
    _write_csv(output / "receiver_situation_final.csv", CURRENT_SITUATION_FIELDS, final_situation)
    received_db = output / "received_states.db"
    save_records_to_sqlite(decoded_records, str(received_db))
    received_records = read_records_from_sqlite(str(received_db))
    _verify_sqlite_roundtrip(decoded_records, received_records)
    _write_csv(output / "precision_error_report.csv", REAL_PRECISION_FIELDS, precision_rows)

    summary = {
        "source_snapshot_count": len(list(source_directory.glob("*.json"))),
        "source_record_count": len(source_rows) + parse_errors,
        "selected_record_count": len(source_rows),
        "encoded_frame_count": len(frames),
        "decoded_record_count": len(decoded_records),
        "valid_decoded_count": sum(record["message_valid"] is True for record in decoded_records),
        "parse_or_encode_error_count": parse_errors,
        "final_target_count": len(final_situation),
        "precision_row_count": len(precision_rows),
        "precision_passed_count": sum(row["passed"] is True for row in precision_rows),
    }
    (output / "experiment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def run_m3(project_root: Path | None = None) -> dict[str, int]:
    """执行 M3 读取、解码、航迹、当前态势及选做持久化流程。"""
    """完成 M3 必做和选做路径：CSV、SQLite 重读查询、经纬度航迹图。"""
    root = project_root or Path(__file__).resolve().parents[2]
    package = root / "student_package"
    output = package / "output"
    output.mkdir(parents=True, exist_ok=True)

    data = (package / "data" / "partner_messages_multitime.bin").read_bytes()
    decoded = decode_message_stream(data)
    tracks = build_tracks(decoded)
    current_situation = build_current_situation(decoded)

    _write_csv(output / "decoded_multitime.csv", DECODED_FIELDS, decoded)
    _write_csv(output / "track_table.csv", TRACK_FIELDS, tracks)
    _write_csv(output / "current_situation.csv", CURRENT_SITUATION_FIELDS, current_situation)
    db_path = output / "states.db"
    save_records_to_sqlite(decoded, str(db_path))
    reloaded = read_records_from_sqlite(str(db_path))
    _verify_sqlite_roundtrip(decoded, reloaded)
    query_rows = query_records_by_target(str(db_path), current_situation[0]["target_id"])
    _write_csv(output / "sqlite_query_result.csv", SQLITE_QUERY_FIELDS, query_rows)
    plot_trajectories(decoded, str(output / "m3_trajectory.png"))
    return {
        "input_bytes": len(data),
        "decoded_records": len(decoded),
        "track_records": len(tracks),
        "current_targets": len(current_situation),
        "sqlite_records": len(reloaded),
        "sqlite_query_rows": len(query_rows),
    }


if __name__ == "__main__":
    result = run_m3()
    print("M3 完成：" + "，".join(f"{name}={count}" for name, count in result.items()))
