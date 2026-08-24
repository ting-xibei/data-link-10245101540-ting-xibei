from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import platform
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


MIN_PYTHON = (3, 10)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    required: bool = True


def check_python() -> CheckResult:
    passed = sys.version_info >= MIN_PYTHON
    return CheckResult(
        "Python版本",
        passed,
        f"当前 {platform.python_version()}，要求 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 及以上",
    )


def check_module(
    module_name: str,
    minimum: tuple[int, ...],
    maximum_exclusive: tuple[int, ...],
) -> CheckResult:
    try:
        specification = importlib.util.find_spec(module_name)
        if specification is None:
            return CheckResult(f"依赖 {module_name}", False, "未找到可导入模块")
        version = importlib.metadata.version(module_name)
        parts = tuple(int(part) for part in re.findall(r"\d+", version)[:3])
    except Exception as exc:
        return CheckResult(f"依赖 {module_name}", False, f"检测失败：{exc}")
    passed = parts >= minimum and parts < maximum_exclusive
    requirement = f">={'.'.join(map(str, minimum))}, <{'.'.join(map(str, maximum_exclusive))}"
    return CheckResult(f"依赖 {module_name}", passed, f"已安装 {version}，要求 {requirement}")


def check_virtual_environment(project_root: Path) -> CheckResult:
    expected_prefix = (project_root / ".venv").resolve()
    actual_prefix = Path(sys.prefix).resolve()
    config_path = expected_prefix / "pyvenv.cfg"
    include_system_packages = None
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "include-system-site-packages":
                include_system_packages = value.strip().lower()
                break
    except OSError as exc:
        return CheckResult("独立虚拟环境", False, f"无法读取 {config_path}：{exc}")
    passed = (
        sys.prefix != sys.base_prefix
        and actual_prefix == expected_prefix
        and include_system_packages == "false"
    )
    detail = (
        f"当前={actual_prefix}；要求={expected_prefix}；"
        f"include-system-site-packages={include_system_packages}"
    )
    return CheckResult("独立虚拟环境", passed, detail)


def check_utf8_and_write(workspace: Path) -> CheckResult:
    test_directory = workspace / f"env_check_{uuid.uuid4().hex}"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        test_directory.mkdir()
        target = test_directory / "中文 空格 UTF-8.json"
        payload = {"status": "正常", "value": 0, "missing": None}
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        loaded = json.loads(target.read_text(encoding="utf-8"))
        target.unlink()
        test_directory.rmdir()
        passed = loaded == payload
        return CheckResult("UTF-8与目录读写", passed, f"测试目录：{workspace}")
    except Exception as exc:
        try:
            target = test_directory / "中文 空格 UTF-8.json"
            if target.exists():
                target.unlink()
            if test_directory.exists():
                test_directory.rmdir()
        except Exception:
            pass
        return CheckResult("UTF-8与目录读写", False, str(exc))


def check_sqlite() -> CheckResult:
    try:
        sqlite3 = importlib.import_module("sqlite3")
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE smoke_test(value INTEGER, note TEXT NULL)")
        connection.execute("INSERT INTO smoke_test VALUES (?, ?)", (0, None))
        row = connection.execute("SELECT value, note FROM smoke_test").fetchone()
        connection.close()
        return CheckResult("SQLite选做路径", row == (0, None), f"读取结果：{row}", required=False)
    except Exception as exc:
        return CheckResult("SQLite选做路径", False, f"{exc}；继续使用CSV必做路径", required=False)


def check_paths(project_root: Path, student_mode: bool) -> CheckResult:
    required = [
        project_root / "student_package",
        project_root / "student_package" / "data",
        project_root / "student_package" / "schema",
        project_root / "student_package" / "templates",
        project_root / "student_package" / "src_skeleton",
        project_root / "environment",
        project_root / "environment" / "run_student_checks.py",
        project_root / "student_package" / "data" / "raw_states.json",
        project_root / "student_package" / "data" / "partner_messages_sample.bin",
        project_root / "student_package" / "data" / "partner_messages_multitime.bin",
        project_root / "student_package" / "data" / "m5" / "anomaly_cases.csv",
        project_root / "student_package" / "schema" / "teaching_message_spec.md",
        project_root / "student_package" / "schema" / "unified_model.json",
        project_root / "student_package" / "guides" / "opensky_interface_summary.md",
        project_root / "student_package" / "guides" / "m1_guided_questions.md",
        project_root / "student_package" / "templates" / "checkpoint_switch.md",
        project_root / "student_package" / "templates" / "submission_checklist.md",
    ]
    if student_mode:
        internal_paths = [
            project_root / "experiment",
            project_root / "ta_reference_package",
            project_root / "tests",
            project_root / "test_records",
            project_root / "student_package" / "data" / "opensky_real" / "roundtrip_report.csv",
        ]
        leaked = [str(path) for path in internal_paths if path.exists()]
        if leaked:
            return CheckResult("正式目录结构", False, "学生包包含内部内容：" + "；".join(leaked))
    else:
        required.extend(
            [
                project_root / "ta_reference_package",
                project_root / "ta_reference_package" / "checkpoints",
                project_root / "ta_reference_package" / "reference_implementation",
                project_root / "ta_reference_package" / "expected_results",
                project_root / "ta_reference_package" / "case_manifest_internal.csv",
                project_root / "environment" / "run_all_checks.py",
                project_root / "environment" / "run_full_trial.py",
                project_root / "environment" / "build_release_packages.py",
                project_root / "test_records",
                project_root / "test_records" / "environment_trial_record_template.md",
                project_root / "test_records" / "module_trial_record_template.md",
                project_root / "tests" / "test_reference_pipeline.py",
                project_root / "manifest.csv",
                project_root / "release_notes.md",
            ]
        )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return CheckResult("正式目录结构", False, "缺少：" + "；".join(missing))
    student_ta_leaks = list((project_root / "student_package").rglob("*reference_implementation*"))
    if student_ta_leaks:
        return CheckResult("正式目录结构", False, "学生包中发现助教参考实现路径")
    return CheckResult("正式目录结构", True, f"根目录：{project_root}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查暑期学校统一Python环境。")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="工作区根目录，默认取脚本上一级目录。",
    )
    parser.add_argument(
        "--student-mode",
        action="store_true",
        help="只检查学生候选包所需目录，并确认未包含助教内部目录。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    writable_root = (
        project_root / "student_package" / "output"
        if args.student_mode
        else project_root / "test_records"
    )
    results = [check_python()]
    results.extend(
        [
            check_module("pandas", (2, 0), (3, 0)),
            check_module("matplotlib", (3, 7), (4, 0)),
        ]
    )
    results.extend(
        [
            check_virtual_environment(project_root),
            check_utf8_and_write(writable_root),
            check_sqlite(),
            check_paths(project_root, args.student_mode),
        ]
    )

    print(f"操作系统：{platform.platform()}")
    print(f"Python可执行文件：{sys.executable}")
    print(f"当前目录：{Path.cwd()}")
    print()
    for result in results:
        marker = "PASS" if result.passed else "FAIL" if result.required else "WARN"
        print(f"[{marker}] {result.name}：{result.detail}")

    required_results = [result for result in results if result.required]
    failed = [result for result in required_results if not result.passed]
    optional_results = [result for result in results if not result.required]
    print()
    print(f"必做检查：{len(required_results) - len(failed)}/{len(required_results)}项通过")
    if optional_results:
        available = sum(result.passed for result in optional_results)
        print(f"选做检查：{available}/{len(optional_results)}项可用；不可用时按降级路径继续")
    if failed:
        print("请先修复失败项，再进行模块试跑。")
        return 1
    print("环境基础检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
