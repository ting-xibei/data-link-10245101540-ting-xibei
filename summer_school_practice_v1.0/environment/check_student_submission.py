from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STUDENT_ROOT = PROJECT_ROOT / "student_package"
OUTPUT_ROOT = STUDENT_ROOT / "output"
DOCS_ROOT = STUDENT_ROOT / "docs"


@dataclass
class Result:
    name: str
    passed: bool
    detail: str


def require_file(relative: str, *, nonempty: bool = True) -> Result:
    path = STUDENT_ROOT / relative
    exists = path.is_file()
    has_content = exists and (not nonempty or path.stat().st_size > 0)
    return Result(relative, has_content, "已找到" if has_content else "缺少或为空")


def require_one(name: str, candidates: list[str]) -> Result:
    paths = [STUDENT_ROOT / candidate for candidate in candidates]
    found = next((path for path in paths if path.is_file() and path.stat().st_size > 0), None)
    detail = str(found.relative_to(STUDENT_ROOT)) if found else "可接受：" + "、".join(candidates)
    return Result(name, found is not None, detail)


def check_code() -> Result:
    candidates = [STUDENT_ROOT / "src", STUDENT_ROOT / "src_skeleton"]
    files = [path for root in candidates if root.is_dir() for path in root.glob("*.py")]
    if not files:
        return Result("M2—M6程序", False, "src/或src_skeleton/中没有Python程序")
    unfinished = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "raise NotImplementedError" in text or "TODO：接入" in text:
            unfinished.append(path.name)
    if unfinished:
        return Result("M2—M6程序", False, "仍含未实现骨架：" + "、".join(sorted(unfinished)))
    return Result("M2—M6程序", True, f"Python文件数={len(files)}")


def check_csv(relative: str, allow_empty_rows: bool = False) -> Result:
    path = OUTPUT_ROOT / relative
    if not path.is_file() or path.stat().st_size == 0:
        return Result(f"output/{relative}", False, "缺少或为空")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            has_header = bool(reader.fieldnames)
        passed = has_header and (allow_empty_rows or bool(rows))
        return Result(f"output/{relative}", passed, f"字段数={len(reader.fieldnames or [])}，记录数={len(rows)}")
    except Exception as exc:
        return Result(f"output/{relative}", False, f"CSV无法读取：{exc}")


def check_ndjson(relative: str) -> Result:
    path = OUTPUT_ROOT / relative
    if not path.is_file() or path.stat().st_size == 0:
        return Result(f"output/{relative}", False, "缺少或为空")
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = [json.loads(line) for line in lines]
        passed = bool(rows) and all(isinstance(row, dict) for row in rows)
        return Result(f"output/{relative}", passed, f"对象数={len(rows)}")
    except Exception as exc:
        return Result(f"output/{relative}", False, f"NDJSON无法读取：{exc}")


def run_checks() -> list[Result]:
    results = [
        check_code(),
        require_file("SUBMISSION_README.md"),
        require_file("output/encoded_messages.bin"),
        check_csv("decoded_partner_states.csv"),
        check_csv("validation_log.csv", allow_empty_rows=True),
        check_csv("roundtrip_report.csv"),
        check_csv("decoded_multitime.csv"),
        check_csv("track_table.csv"),
        check_csv("current_situation.csv"),
        check_csv("llm_mapping_candidate.csv"),
        check_csv("verified_mapping_table.csv"),
        check_ndjson("unified_situation.ndjson"),
        check_csv("alert_log.csv", allow_empty_rows=True),
        check_csv("quality_situation.csv"),
        require_one("M1系统处理流程图", ["docs/M1_system_flow.pdf", "docs/M1_system_flow.png", "docs/M1_system_flow.md"]),
        require_one("M1接口、通信与风险说明", ["docs/M1_interface_risk.pdf", "docs/M1_interface_risk.docx", "docs/M1_interface_risk.md"]),
        require_one("M4映射核验说明", ["docs/M4_mapping_review.pdf", "docs/M4_mapping_review.docx", "docs/M4_mapping_review.md"]),
        require_one("M6展示材料", ["docs/M6_presentation.pdf", "docs/M6_presentation.pptx"]),
    ]
    encoded = OUTPUT_ROOT / "encoded_messages.bin"
    if encoded.is_file() and encoded.stat().st_size > 0:
        size = encoded.stat().st_size
        results.append(Result("TeachingLink帧长度", size % 41 == 0, f"{size}字节，帧数={size // 41}，要求能被41整除"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="检查个人M1—M6提交材料。")
    parser.add_argument("--strict", action="store_true", help="存在缺项时返回失败，供最终提交使用。")
    args = parser.parse_args()

    results = run_checks()
    for result in results:
        marker = "PASS" if result.passed else "FAIL" if args.strict else "TODO"
        print(f"[{marker}] {result.name}：{result.detail}")
    failed = [result for result in results if not result.passed]
    print(f"\n提交检查：{len(results) - len(failed)}/{len(results)}项通过")
    if failed and not args.strict:
        print("当前为进度检查；最终提交前请使用 --strict。")
    return 1 if args.strict and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
