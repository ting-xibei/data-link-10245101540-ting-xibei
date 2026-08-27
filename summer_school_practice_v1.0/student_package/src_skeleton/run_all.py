"""M6 综合运行入口。

这个文件不重新实现 M2--M5 的算法，而是负责把已经完成的四个模块组织成
一条可以重复执行的实验流程。它主要承担以下职责：

1. 从一个干净的 ``output`` 目录开始，避免误用上一次运行留下的结果；
2. 按 M2 -> M3 -> M4 -> M5 的顺序调用各模块公开的 ``run_m*`` 函数；
3. 在相邻阶段之间重新读取关键文件，检查文件格式、记录数量和重要字段；
4. 对 SQLite、统一态势和质量检查结果进行额外的集成验证；
5. 汇总各阶段统计信息，并生成 M6 的运行说明和展示提纲。

因此，M6 的核心价值是“调度 + 接口验收 + 可重复运行”，而不是增加新的
数据处理算法。如果 M2--M5 仍是空占位，本脚本也无法产生有效实验成果。
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

from m2_protocol import FRAME_SIZE, run_m2
from m3_tracks import run_m3, run_real_opensky_validation
from m4_mapping import run_m4
from m5_quality import run_m5


# 所有路径都由本文件所在位置推导，而不是直接使用当前终端目录。这样无论
# 用户从哪个目录执行脚本，程序都能定位到同一份输入、输出和文档目录。
STUDENT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = STUDENT_PACKAGE_ROOT.parent
OUTPUT_ROOT = STUDENT_PACKAGE_ROOT / "output"
DOCS_ROOT = STUDENT_PACKAGE_ROOT / "docs"
# 每个 run_m* 函数都会返回本阶段的记录数、帧数等统计信息。这里集中保存，
# 最后用于打印运行摘要以及填写 SUBMISSION_README.md。
STAGE_RESULTS: dict[str, dict[str, int]] = {}


def prepare_output_directory() -> None:
    """准备一个干净且可写的输出目录。

    M6 要求能够从空 ``output`` 目录重新生成全部结果，所以运行前需要删除旧
    生成物。说明性的 ``output/README.md`` 不属于实验计算结果，因此予以保留。
    删除前先尝试以读写方式打开文件，以便在文件被 Excel 等程序占用时给出
    明确错误，而不是在运行到一半时才失败。
    """
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    generated_items = [item for item in OUTPUT_ROOT.iterdir() if item.name != "README.md"]
    # 第一遍只检查文件是否可写，不立即删除，避免部分文件已经删除后才发现
    # 另一个文件被占用，造成 output 处于半清理状态。
    for item in generated_items:
        if item.is_file():
            try:
                with item.open("rb+"):
                    pass
            except PermissionError as exc:
                raise PermissionError(f"输出文件正被占用，请关闭后重试：{item.name}") from exc
    # 所有文件均通过占用检查后，再统一执行清理。
    for item in generated_items:
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def parse() -> None:
    """运行 M2：完成解析、编码、接收解码、校验和量化误差检查。

    ``run_m2`` 会读取 ``raw_states.json``，把有效 OpenSky 状态封装为固定
    41 字节 TeachingLink 帧，再从接收方角度解码这些帧并写出结构化结果。
    """
    STAGE_RESULTS["m2"] = run_m2(PROJECT_ROOT)


def encode() -> None:
    """验收 M2 的二进制输出是否满足固定帧边界。

    编码工作已经由 ``run_m2`` 完成；这里不是再次编码，而是从 M6 集成层面
    重新读取文件，确认文件非空且总长度能被 41 整除。
    """
    message_path = OUTPUT_ROOT / "encoded_messages.bin"
    data = message_path.read_bytes()
    if not data or len(data) % FRAME_SIZE:
        raise ValueError("M2 二进制消息流为空或未按 41 字节帧对齐。")


def decode_validate() -> None:
    """重新读取 M2 的接收结果，验证其可以作为后续阶段的可靠输入。

    除了检查所有正常输出帧的 ``message_valid``，还要求量化往返报告全部通过。
    ``validation_log.csv`` 允许包含程序主动构造的错误帧测试记录，因此这里只
    验证它能够被正确读取，而不要求日志为空。
    """
    rows = _read_csv(OUTPUT_ROOT / "decoded_partner_states.csv")
    if not rows or not all(row["message_valid"] == "True" for row in rows):
        raise ValueError("M2 解码结果缺失或包含未通过接收校验的输出记录。")
    _read_csv(OUTPUT_ROOT / "validation_log.csv")
    roundtrip = _read_csv(OUTPUT_ROOT / "roundtrip_report.csv")
    if not roundtrip or not all(row["passed"] == "True" for row in roundtrip):
        raise ValueError("M2 量化往返误差检查未全部通过。")


def persist_records(optional: bool = True) -> None:
    """运行 M3，并验证选做的 SQLite 持久化结果。

    M3 使用课程提供的多时刻 TeachingLink 帧，生成航迹和当前态势。需要注意：
    它不是直接处理 M2 生成的三帧教学样例，而是使用专门准备的 9 帧多时刻
    数据，以便验证按目标和时间进行航迹关联的能力。
    """
    if not optional:
        raise ValueError("M6 本次实验已选择 SQLite 持久化，optional 必须为 True。")
    STAGE_RESULTS["m3"] = run_m3(PROJECT_ROOT)
    database = OUTPUT_ROOT / "states.db"
    if not database.is_file():
        raise ValueError("M3 SQLite 输出未生成。")
    # 重新连接数据库并查询实际行数，证明数据库文件不是“只生成未验证”。
    connection = sqlite3.connect(database)
    try:
        count = connection.execute("SELECT COUNT(*) FROM state_record").fetchone()[0]
    finally:
        connection.close()
    if count != STAGE_RESULTS["m3"]["sqlite_records"]:
        raise ValueError("M3 SQLite 重读记录数不一致。")

    # 手册 6.6 的真实数据验证复用本人完成的 M2--M3 实现。把它接入统一入口，
    # 可确保 output 被清空后，这组验证成果也能随普通 M3 结果一起重新生成。
    STAGE_RESULTS["m3_real"] = run_real_opensky_validation(PROJECT_ROOT)
    real_result = STAGE_RESULTS["m3_real"]
    if real_result["decoded_record_count"] != real_result["valid_decoded_count"]:
        raise ValueError("M3 OpenSky 真实数据包含未通过接收校验的解码记录。")
    if real_result["precision_row_count"] != real_result["precision_passed_count"]:
        raise ValueError("M3 OpenSky 真实数据精度检查未全部通过。")
    transmitted = (OUTPUT_ROOT / "transmitted_frames.bin").read_bytes()
    expected_length = real_result["encoded_frame_count"] * FRAME_SIZE
    if len(transmitted) != expected_length:
        raise ValueError("M3 OpenSky 真实数据发送帧长度与编码帧数不一致。")


def build_tracks() -> None:
    """验收 M3 的航迹表和当前态势表。

    M3 已在 ``persist_records`` 阶段完成实际计算；这里重新读取 CSV，并检查
    当前态势仍保留跨模块需要的高度来源、时间来源和消息有效性语义。
    """
    tracks = _read_csv(OUTPUT_ROOT / "track_table.csv")
    situation = _read_csv(OUTPUT_ROOT / "current_situation.csv")
    if not tracks or not situation:
        raise ValueError("M3 航迹或当前态势输出为空。")
    required = {"target_id", "alt_type", "time_source", "message_valid"}
    if not required.issubset(situation[0]):
        raise ValueError("M3 当前态势丢失高度来源、时间来源或消息有效性字段。")


def map_unified() -> None:
    """运行 M4，把 OpenSky 与 TeachingLink 转换为统一态势模型。

    M4 会保留 AI 候选作为审查输入，但正式转换只使用人工核验后的规则。
    集成层随后检查每条正式规则都标记为已核验，并确认统一 NDJSON 同时包含
    OpenSky 和 TeachingLink 两种来源。
    """
    STAGE_RESULTS["m4"] = run_m4(PROJECT_ROOT)
    verified = _read_csv(OUTPUT_ROOT / "verified_mapping_table.csv")
    if not verified or not all(row["verified"] == "True" for row in verified):
        raise ValueError("M4 正式映射表缺失或包含未核验规则。")
    messages = _read_ndjson(OUTPUT_ROOT / "unified_situation.ndjson")
    if not messages or {message["source"] for message in messages} != {"OpenSky", "TeachingLink"}:
        raise ValueError("M4 统一消息未同时覆盖 OpenSky 与 TeachingLink。")


def check_quality() -> None:
    """运行 M5，并核对告警日志与质量态势的完整性。

    M5 使用专门的异常样例验证位置缺失、数据延迟、联合键重复和航向越界等
    固定规则。这里比较磁盘文件行数与 ``run_m5`` 返回的统计，防止导出遗漏。
    """
    STAGE_RESULTS["m5"] = run_m5(PROJECT_ROOT)
    alerts = _read_csv(OUTPUT_ROOT / "alert_log.csv")
    quality = _read_csv(OUTPUT_ROOT / "quality_situation.csv")
    if not quality or len(quality) != STAGE_RESULTS["m5"]["quality_rows"]:
        raise ValueError("M5 质量态势输出不完整。")
    if len(alerts) != STAGE_RESULTS["m5"]["alerts"]:
        raise ValueError("M5 告警日志数量不一致。")


def export_results() -> None:
    """执行最终跨模块验收，并生成 M6 说明材料。

    ``_verify_pipeline_outputs`` 是最后一道集成门槛：只有关键文件均存在且核心
    协议/语义字段没有丢失时，才生成综合运行说明和五页展示提纲。
    """
    _verify_pipeline_outputs()
    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    _write_submission_readme(STUDENT_PACKAGE_ROOT / "SUBMISSION_README.md")
    _write_presentation_outline(DOCS_ROOT / "m6_presentation_outline.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    """以字段字典形式重新读取 CSV，模拟下游模块消费上游文件。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    """逐行读取统一消息，确保每个非空行都是独立 JSON 对象。"""
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
    """M6 总体验收：检查关键文件及跨模块核心字段。

    这里不重复 M2--M5 的内部算法测试，而是关注集成后最容易发生的问题：
    文件遗漏、输出不可读取，以及协议状态或统一模型语义在 CSV/NDJSON 转换中
    丢失。任何一项不满足都会抛出异常，使 M6 以失败状态结束。
    """
    required_files = [
        "encoded_messages.bin",
        "decoded_partner_states.csv",
        "validation_log.csv",
        "roundtrip_report.csv",
        "decoded_multitime.csv",
        "track_table.csv",
        "current_situation.csv",
        "states.db",
        "receiver_situation_initial.csv",
        "selected_source_states.csv",
        "transmitted_frames.bin",
        "transmission_log.csv",
        "decoded_states.csv",
        "receiver_situation_final.csv",
        "received_states.db",
        "precision_error_report.csv",
        "experiment_summary.json",
        "verified_mapping_table.csv",
        "unified_situation.ndjson",
        "alert_log.csv",
        "quality_situation.csv",
    ]
    missing = [name for name in required_files if not (OUTPUT_ROOT / name).is_file()]
    if missing:
        raise ValueError("M6 缺少关键成果：" + ", ".join(missing))
    # M2 解码结果既要保存物理值，也要保存来源、有效性和帧级结论，否则后续
    # 模块无法区分“字段缺失”“真实零值”和“整帧无效”。
    decoded_fields = set(_read_csv(OUTPUT_ROOT / "decoded_partner_states.csv")[0])
    required_decoded_fields = {"alt_type", "time_source", "message_valid", "status_flags", "validity_flags"}
    if not required_decoded_fields.issubset(decoded_fields):
        raise ValueError("M2 解码结果丢失协议状态或有效性字段。")
    # 统一模型仍须携带高度类型、时间来源和消息有效性，不能在 M4 映射时只
    # 保留经纬度等表面字段。
    for message in _read_ndjson(OUTPUT_ROOT / "unified_situation.ndjson"):
        position, quality = message["position"], message["quality"]
        if "alt_type" not in position or "time_source" not in quality or "message_valid" not in quality:
            raise ValueError("M4 统一消息丢失 alt_type、time_source 或 message_valid。")


def _write_submission_readme(path: Path) -> None:
    """以 M6 模板为骨架，写入本次实际入口、数据量、帧数和已知限制。"""
    m2, m3, m3_real, m4, m5 = (
        STAGE_RESULTS[name] for name in ("m2", "m3", "m3_real", "m4", "m5")
    )
    text = rf"""# M6 综合运行说明

## 基本信息

- 姓名：赵熙焙
- 学号：10245101540
- GitHub用户名：ting-xibei
- Python版本：{sys.version.split()[0]}
- 是否使用SQLite：是
- M4候选来源：依据已保存提示词生成的AI候选

## 安装与运行

先按课程包 `environment/README_environment.md` 建立独立 `.venv`。在课程包根目录执行：

```powershell
.\.venv\Scripts\python.exe student_package\src_skeleton\run_all.py
```

入口会清理 `student_package/output/` 中已有生成物（保留说明性 `README.md`），再从固定输入重新生成全部成果。

## 程序入口

`run_all.py` 的调用顺序为：M2 解析/编码/接收校验 → 41 字节帧对齐核验 → M3 SQLite 持久化、航迹和当前态势 → M3 OpenSky 真实数据验证 → M4 人工核验映射 → M5 一致性检查 → 关键成果重新读取与导出。

## 输入文件

- `data/raw_states.json`：M2 OpenSky 状态向量；
- `data/partner_messages_multitime.bin`：M3 9 帧多时刻 TeachingLink 消息；
- `data/opensky_real/source/`：M3 真实OpenSky冻结快照；
- `data/m4/partner_current_situation.csv`、字段定义和统一模型：M4；
- `data/m5/anomaly_cases.csv`、`data/m5/anomaly_rules.csv`：M5。

## 输出文件

M2：`encoded_messages.bin`、`decoded_partner_states.csv`、`validation_log.csv`、`roundtrip_report.csv`。

M3：`decoded_multitime.csv`、`track_table.csv`、`current_situation.csv`、`states.db`、`sqlite_query_result.csv`、`m3_trajectory.png`。

M3真实数据验证：`receiver_situation_initial.csv`、`selected_source_states.csv`、`transmitted_frames.bin`、`transmission_log.csv`、`decoded_states.csv`、`receiver_situation_final.csv`、`received_states.db`、`precision_error_report.csv`、`experiment_summary.json`。

M4：`llm_mapping_candidate.csv`、`verified_mapping_table.csv`、`unified_situation.ndjson`；核验说明保存为 `docs/M4_mapping_review.md`。

M5：`alert_log.csv`、`quality_situation.csv`。

## 实验结果

- M2：编码 {m2['encoded_frames']} 帧、解码 {m2['decoded_rows']} 条、校验日志 {m2['validation_rows']} 条、量化往返检查 {m2['roundtrip_rows']} 项；
- M3：输入 {m3['input_bytes']} 字节，解码 {m3['decoded_records']} 条，形成 {m3['track_records']} 个航迹点、{m3['current_targets']} 个当前目标，SQLite 重读 {m3['sqlite_records']} 条；
- M3真实数据验证：读取 {m3_real['source_snapshot_count']} 个OpenSky快照、{m3_real['source_record_count']} 条状态，编码并成功解码 {m3_real['decoded_record_count']} 帧，形成 {m3_real['final_target_count']} 个当前目标，{m3_real['precision_passed_count']}/{m3_real['precision_row_count']} 项精度检查通过；
- M4：保留 {m4['candidate_rows']} 条候选，形成 {m4['verified_rows']} 条已核验映射，输出 {m4['unified_records']} 条统一消息；
- M5：检查 {m5['input_records']} 条样例，输出 {m5['alerts']} 条告警和 {m5['quality_rows']} 条质量态势。

## 已知限制

- TeachingLink 为课程自定义教学协议，`message_valid` 只代表帧结构与接收校验，不代表数据真实性或飞行安全；
- OpenSky真实数据验证使用课程包中冻结的3个快照，不代表实时航空态势；
- M5 选做帧异常规则已实现，但固定 M5 样例均为有效帧，真实无效帧仅通过程序内构造测试覆盖；
- M4 的跨源验证基于课程提供的当前态势样例；最终 commit ID 需在提交前由本人填写。

## 最终提交信息

- 仓库链接：https://github.com/ting-xibei/data-link-10245101540-ting-xibei
- 最终commit ID：未提供（提交前填写）
- 最后检查日期：{date.today().isoformat()}
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
- 使用3个真实OpenSky快照验证71条状态、24个目标和497项量化精度；
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
    """按 M6 规定的顺序执行完整流程并返回各阶段统计信息。

    这些小函数有些负责实际调用模块，有些负责验收刚生成的结果。将两类步骤
    分开，可以清楚地判断失败来自“模块计算”还是“模块接口/输出不符合要求”。
    """
    # 0. 建立可重复运行的前提：不依赖旧 output。
    prepare_output_directory()
    # 1. M2 实际处理 OpenSky 教学样例，生成并解码 41 字节帧。
    parse()
    # 2. 从文件层面检查帧边界、接收结论和量化误差。
    encode()
    decode_validate()
    # 3. M3 处理多时刻帧并运行 OpenSky 真实数据验证，随后验收关键字段。
    persist_records(optional=True)
    build_tracks()
    # 4. M4 使用已核验规则统一两种来源的字段与语义。
    map_unified()
    # 5. M5 对固定异常样例执行一致性规则并形成质量态势。
    check_quality()
    # 6. 最终复读所有关键成果，确认完整后才生成 M6 汇总材料。
    export_results()
    return dict(STAGE_RESULTS)


def main() -> int:
    """命令行入口：将异常转换为清晰提示和非零退出码。"""
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
