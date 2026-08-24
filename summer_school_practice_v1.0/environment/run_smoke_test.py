from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SmokeResult:
    name: str
    passed: bool
    detail: str


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "smoke_data"
PROJECT_ROOT = ROOT.parent
PRACTICE_DATA = PROJECT_ROOT / "student_package" / "data"
SCHEMA = PROJECT_ROOT / "student_package" / "schema"
MAPPING_CANDIDATE = PROJECT_ROOT / "student_package" / "reference" / "pre_generated_mapping_candidate.csv"


def read_json() -> SmokeResult:
    path = DATA / "sample.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        passed = value.get("name") == "环境冒烟测试" and value.get("zero") == 0
        return SmokeResult("JSON读取", passed, f"{path.name}，字段数={len(value)}")
    except Exception as exc:
        return SmokeResult("JSON读取", False, str(exc))


def read_binary() -> SmokeResult:
    path = DATA / "sample_frame.bin"
    try:
        value = path.read_bytes()
        passed = len(value) == 41
        return SmokeResult("二进制读取", passed, f"{path.name}，字节数={len(value)}，要求=41")
    except Exception as exc:
        return SmokeResult("二进制读取", False, str(exc))


def read_csv() -> SmokeResult:
    path = DATA / "sample.csv"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        passed = len(rows) == 2 and rows[0]["target_id"] == "000001"
        return SmokeResult("CSV读取", passed, f"{path.name}，记录数={len(rows)}")
    except Exception as exc:
        return SmokeResult("CSV读取", False, str(exc))


def read_ndjson() -> SmokeResult:
    path = DATA / "sample.ndjson"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        passed = len(rows) == 2 and rows[1]["quality"]["message_valid"] is True
        return SmokeResult("NDJSON读取", passed, f"{path.name}，对象数={len(rows)}")
    except Exception as exc:
        return SmokeResult("NDJSON读取", False, str(exc))


def read_practice_inputs() -> SmokeResult:
    try:
        raw = json.loads((PRACTICE_DATA / "raw_states.json").read_text(encoding="utf-8"))
        sample_size = (PRACTICE_DATA / "partner_messages_sample.bin").stat().st_size
        multitime_size = (PRACTICE_DATA / "partner_messages_multitime.bin").stat().st_size
        with (PRACTICE_DATA / "m5" / "anomaly_cases.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            anomaly_rows = list(csv.DictReader(handle))
        unified = json.loads((SCHEMA / "unified_model.json").read_text(encoding="utf-8"))
        passed = (
            len(raw.get("states", [])) == 5
            and sample_size == 3 * 41
            and multitime_size == 9 * 41
            and len(anomaly_rows) == 6
            and "quality" in unified
        )
        detail = f"raw=5，sample={sample_size}字节，multitime={multitime_size}字节，anomaly={len(anomaly_rows)}"
        return SmokeResult("M1-M5正式输入", passed, detail)
    except Exception as exc:
        return SmokeResult("M1-M5正式输入", False, str(exc))


def read_mapping_candidate() -> SmokeResult:
    required_fields = {
        "source_format",
        "input_field",
        "candidate_unified_field",
        "candidate_rule",
        "confidence",
        "review_note",
    }
    try:
        with MAPPING_CANDIDATE.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fields = set(reader.fieldnames or [])
        complete_rows = all(
            row.get("source_format", "").strip()
            and row.get("input_field", "").strip()
            and row.get("candidate_unified_field", "").strip()
            for row in rows
        )
        passed = required_fields.issubset(fields) and bool(rows) and complete_rows
        return SmokeResult("M4预生成候选", passed, f"{MAPPING_CANDIDATE.name}，候选数={len(rows)}")
    except Exception as exc:
        return SmokeResult("M4预生成候选", False, str(exc))


def main() -> int:
    results = [read_json(), read_binary(), read_csv(), read_ndjson(), read_practice_inputs(), read_mapping_candidate()]
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.name}：{result.detail}")
    failed = [result for result in results if not result.passed]
    print(f"总结：{len(results) - len(failed)}/{len(results)}项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
