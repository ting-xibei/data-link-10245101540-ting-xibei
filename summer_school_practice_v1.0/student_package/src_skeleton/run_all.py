from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from m2_protocol import FRAME_SIZE, run_m2
from m3_tracks import run_m3
from m4_mapping import run_m4
from m5_quality import run_m5


STUDENT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = STUDENT_PACKAGE_ROOT.parent
OUTPUT_ROOT = STUDENT_PACKAGE_ROOT / "output"
DOCS_ROOT = STUDENT_PACKAGE_ROOT / "docs"
STAGE_RESULTS: dict[str, dict[str, int]] = {}


def prepare_output_directory() -> None:
    """M6 固定入口先检查输出可写，再清除已有生成物并保留说明 README。"""
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    generated_items = [item for item in OUTPUT_ROOT.iterdir() if item.name != "README.md"]
    for item in generated_items:
        if item.is_file():
            try:
                with item.open("rb+"):
                    pass
            except PermissionError as exc:
                raise PermissionError(f"输出文件正被占用，请关闭后重试：{item.name}") from exc
    for item in generated_items:
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def parse() -> None:
    """执行 M2 的 OpenSky 解析、TeachingLink 编码和接收端解码流程。"""
    STAGE_RESULTS["m2"] = run_m2(PROJECT_ROOT)


def encode() -> None:
    """确认 M2 已生成按 41 字节边界排列的二进制消息流。"""
    message_path = OUTPUT_ROOT / "encoded_messages.bin"
    data = message_path.read_bytes()
    if not data or len(data) % FRAME_SIZE:
        raise ValueError("M2 二进制消息流为空或未按 41 字节帧对齐。")


def decode_validate() -> None:
    """重新读取 M2 解码和校验结果，保证接收阶段成果可被下游使用。"""
    rows = _read_csv(OUTPUT_ROOT / "decoded_partner_states.csv")
    if not rows or not all(row["message_valid"] == "True" for row in rows):
        raise ValueError("M2 解码结果缺失或包含未通过接收校验的输出记录。")
    _read_csv(OUTPUT_ROOT / "validation_log.csv")
    roundtrip = _read_csv(OUTPUT_ROOT / "roundtrip_report.csv")
    if not roundtrip or not all(row["passed"] == "True" for row in roundtrip):
        raise ValueError("M2 量化往返误差检查未全部通过。")


def persist_records(optional: bool = True) -> None:
    """执行 M3；本次选择 SQLite 持久化及其重读验证。"""
    if not optional:
        raise ValueError("M6 本次实验已选择 SQLite 持久化，optional 必须为 True。")
    STAGE_RESULTS["m3"] = run_m3(PROJECT_ROOT)
    database = OUTPUT_ROOT / "states.db"
    if not database.is_file():
        raise ValueError("M3 SQLite 输出未生成。")
    connection = sqlite3.connect(database)
    try:
        count = connection.execute("SELECT COUNT(*) FROM state_record").fetchone()[0]
    finally:
        connection.close()
    if count != STAGE_RESULTS["m3"]["sqlite_records"]:
        raise ValueError("M3 SQLite 重读记录数不一致。")


def build_tracks() -> None:
    """M3 已在持久化阶段生成航迹表、当前态势和航迹图；此处核验关键成果。"""
    tracks = _read_csv(OUTPUT_ROOT / "track_table.csv")
    situation = _read_csv(OUTPUT_ROOT / "current_situation.csv")
    if not tracks or not situation:
        raise ValueError("M3 航迹或当前态势输出为空。")
    required = {"target_id", "alt_type", "time_source", "message_valid"}
    if not required.issubset(situation[0]):
        raise ValueError("M3 当前态势丢失高度来源、时间来源或消息有效性字段。")


def map_unified() -> None:
    """执行 M4 已人工核验的语义映射，生成两种来源的统一消息。"""
    STAGE_RESULTS["m4"] = run_m4(PROJECT_ROOT)
    verified = _read_csv(OUTPUT_ROOT / "verified_mapping_table.csv")
    if not verified or not all(row["verified"] == "True" for row in verified):
        raise ValueError("M4 正式映射表缺失或包含未核验规则。")
    messages = _read_ndjson(OUTPUT_ROOT / "unified_situation.ndjson")
    if not messages or {message["source"] for message in messages} != {"OpenSky", "TeachingLink"}:
        raise ValueError("M4 统一消息未同时覆盖 OpenSky 与 TeachingLink。")


def check_quality() -> None:
    """执行 M5 固定一致性检查和已选择的帧校验异常检查。"""
    STAGE_RESULTS["m5"] = run_m5(PROJECT_ROOT)
    alerts = _read_csv(OUTPUT_ROOT / "alert_log.csv")
    quality = _read_csv(OUTPUT_ROOT / "quality_situation.csv")
    if not quality or len(quality) != STAGE_RESULTS["m5"]["quality_rows"]:
        raise ValueError("M5 质量态势输出不完整。")
    if len(alerts) != STAGE_RESULTS["m5"]["alerts"]:
        raise ValueError("M5 告警日志数量不一致。")


def export_results() -> None:
    """复读全部关键成果，并生成 M6 README 与五页展示提纲。"""
    _verify_pipeline_outputs()
    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    _write_submission_readme(PROJECT_ROOT / "SUBMISSION_README.md")
    _write_presentation_outline(DOCS_ROOT / "m6_presentation_outline.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"统一消息第 {line_number} 行不是 JSON 对象。")
                messages.append(value)
    return messages


def _verify_pipeline_outputs() -> None:
    """M6 自检：所有关键文件可重读，关键协议和语义字段未在中途丢失。"""
    required_files = [
        "encoded_messages.bin",
        "decoded_partner_states.csv",
        "validation_log.csv",
        "roundtrip_report.csv",
        "decoded_multitime.csv",
        "track_table.csv",
        "current_situation.csv",
        "states.db",
        "verified_mapping_table.csv",
        "unified_situation.ndjson",
        "alert_log.csv",
        "quality_situation.csv",
    ]
    missing = [name for name in required_files if not (OUTPUT_ROOT / name).is_file()]
    if missing:
        raise ValueError("M6 缺少关键成果：" + ", ".join(missing))
    decoded_fields = set(_read_csv(OUTPUT_ROOT / "decoded_partner_states.csv")[0])
    required_decoded_fields = {"alt_type", "time_source", "message_valid", "status_flags", "validity_flags"}
    if not required_decoded_fields.issubset(decoded_fields):
        raise ValueError("M2 解码结果丢失协议状态或有效性字段。")
    for message in _read_ndjson(OUTPUT_ROOT / "unified_situation.ndjson"):
        position, quality = message["position"], message["quality"]
        if "alt_type" not in position or "time_source" not in quality or "message_valid" not in quality:
            raise ValueError("M4 统一消息丢失 alt_type、time_source 或 message_valid。")


def _write_submission_readme(path: Path) -> None:
    """以 M6 模板为骨架，写入本次实际入口、数据量、帧数和已知限制。"""
    m2, m3, m4, m5 = (STAGE_RESULTS[name] for name in ("m2", "m3", "m4", "m5"))
    text = rf"""# M6 综合运行说明

## 基本信息

- 姓名：未提供（提交前填写）
- 学号：未提供（提交前填写）
- GitHub用户名：未提供（提交前填写）
- Python版本：{sys.version.split()[0]}
- 是否使用SQLite：是
- M4候选来源：学校预生成候选

## 安装与运行

先按课程包 `environment/README_environment.md` 建立独立 `.venv`。在课程包根目录执行：

```powershell
.\.venv\Scripts\python.exe student_package\src_skeleton\run_all.py
```

入口会清理 `student_package/output/` 中已有生成物（保留说明性 `README.md`），再从固定输入重新生成全部成果。

## 程序入口

`run_all.py` 的调用顺序为：M2 解析/编码/接收校验 → 41 字节帧对齐核验 → M3 SQLite 持久化、航迹和当前态势 → M4 人工核验映射 → M5 一致性检查 → 关键成果重新读取与导出。

## 输入文件

- `data/raw_states.json`：M2 OpenSky 状态向量；
- `data/partner_messages_multitime.bin`：M3 9 帧多时刻 TeachingLink 消息；
- `data/m4/partner_current_situation.csv`、字段定义和统一模型：M4；
- `data/m5/anomaly_cases.csv`、`data/m5/anomaly_rules.csv`：M5。

## 输出文件

M2：`encoded_messages.bin`、`decoded_partner_states.csv`、`validation_log.csv`、`roundtrip_report.csv`。

M3：`decoded_multitime.csv`、`track_table.csv`、`current_situation.csv`、`states.db`、`sqlite_query_result.csv`、`m3_trajectory.png`。

M4：`llm_mapping_candidate.csv`、`verified_mapping_table.csv`、`unified_situation.ndjson`、`m4_ai_mapping_review.md`。

M5：`alert_log.csv`、`quality_situation.csv`。

## 实验结果

- M2：编码 {m2['encoded_frames']} 帧、解码 {m2['decoded_rows']} 条、校验日志 {m2['validation_rows']} 条、量化往返检查 {m2['roundtrip_rows']} 项；
- M3：输入 {m3['input_bytes']} 字节，解码 {m3['decoded_records']} 条，形成 {m3['track_records']} 个航迹点、{m3['current_targets']} 个当前目标，SQLite 重读 {m3['sqlite_records']} 条；
- M4：保留 {m4['candidate_rows']} 条候选，形成 {m4['verified_rows']} 条已核验映射，输出 {m4['unified_records']} 条统一消息；
- M5：检查 {m5['input_records']} 条样例，输出 {m5['alerts']} 条告警和 {m5['quality_rows']} 条质量态势。

## 已知限制

- TeachingLink 为课程自定义教学协议，`message_valid` 只代表帧结构与接收校验，不代表数据真实性或飞行安全；
- M5 选做帧异常规则已实现，但固定 M5 样例均为有效帧，真实无效帧仅通过程序内构造测试覆盖；
- M4 的跨源验证基于课程提供的当前态势样例；姓名、学号、仓库链接和最终 commit ID 需在提交前由本人填写。

## 最终提交信息

- 仓库链接：未提供（提交前填写）
- 最终commit ID：未提供（提交前填写）
- 最后检查日期：运行 M6 后填写
"""
    path.write_text(text, encoding="utf-8")


def _write_presentation_outline(path: Path) -> None:
    """生成不超过五页的 M6 成果展示提纲。"""
    text = """# M6 五页成果展示提纲

## 第1页：问题、边界与完整处理链

- 输入为 OpenSky 状态向量、TeachingLink 多时刻帧、M4/M5 固定样例；
- 处理链：解析 → 41 字节编码 → 传输/接收校验 → SQLite → 航迹/态势 → 语义映射 → 质量检查；
- TeachingLink 是课程教学协议，不是行业标准。

## 第2页：发送方与接收方编解码

- 从 `raw_states.json` 解析字段、时间来源和高度来源；
- 按大端、固定 41 字节、比例因子、偏置和有效位生成 TeachingLink 帧；
- 接收端检查 magic、版本、长度、校验和、保留位与标志一致性，并报告量化误差。

## 第3页：持久化、航迹与当前态势

- 对 9 帧多时刻消息按 `target_id` 和时间关联；
- 将有效记录保存至 SQLite 并重读核验；
- 展示经纬度航迹、每个目标的最新态势及位置缺失的处理方式。

## 第4页：人工核验后的语义映射

- 候选映射不是最终规则，依据字段定义修正纬经度、高度偏置、呼号有效位和时间来源；
- OpenSky 与 TeachingLink 均输出统一 NDJSON；
- 保留 `alt_type`、`time_source`、有效性和 `message_valid` 语义。

## 第5页：一致性结果、改进与限制

- 固定规则识别位置缺失、延迟、联合键重复和航向越界；
- 使用 HIGH/MEDIUM/NONE 合成 ERROR/WARNING/NORMAL；
- 说明帧异常选做规则、样例覆盖限制和后续可扩展方向。
"""
    path.write_text(text, encoding="utf-8")


def run_pipeline() -> dict[str, dict[str, int]]:
    prepare_output_directory()
    parse()
    encode()
    decode_validate()
    persist_records(optional=True)
    build_tracks()
    map_unified()
    check_quality()
    export_results()
    return dict(STAGE_RESULTS)


def main() -> int:
    try:
        results = run_pipeline()
    except Exception as exc:
        print(f"M6 失败：{exc}")
        return 1
    summary = "；".join(f"{name}={values}" for name, values in results.items())
    print("M6 完成：" + summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
