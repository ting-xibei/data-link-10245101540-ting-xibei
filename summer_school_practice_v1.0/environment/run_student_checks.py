from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(name: str, command: list[str]) -> bool:
    print(f"\n=== {name} ===", flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    print(f"{name} exit={completed.returncode}", flush=True)
    return completed.returncode == 0


def check_python_skeletons() -> bool:
    skeleton_root = ROOT / "student_package" / "src_skeleton"
    errors: list[str] = []
    for path in sorted(skeleton_root.glob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            errors.append(f"{path.name}: {exc}")
    if errors:
        print("[FAIL] 学生代码骨架语法：" + "；".join(errors))
        return False
    print(f"[PASS] 学生代码骨架语法：{len(list(skeleton_root.glob('*.py')))}个文件")
    return True


def main() -> int:
    checks = [
        run("学生环境检查", [sys.executable, "environment/environment_check.py", "--student-mode"]),
        run("学生文件冒烟测试", [sys.executable, "environment/run_smoke_test.py"]),
        check_python_skeletons(),
    ]
    print(f"\n学生包总检查：{sum(checks)}/{len(checks)}项通过")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
