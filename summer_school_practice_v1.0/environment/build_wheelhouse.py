from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="为当前操作系统和Python版本准备离线wheelhouse。")
    parser.add_argument("--output", type=Path, default=ROOT / "environment" / "wheelhouse")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--requirement",
        str(ROOT / "environment" / "requirements.txt"),
        "--dest",
        str(output),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print("wheelhouse生成失败。请确认当前电脑可联网，且操作系统、CPU架构和Python版本与机房一致。")
        return completed.returncode
    wheels = sorted(path.name for path in output.glob("*.whl"))
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "requirements": "environment/requirements.txt",
        "wheel_count": len(wheels),
        "wheels": wheels,
        "note": "仅适用于兼容的操作系统、CPU架构和Python版本；机房环境不一致时必须重新生成。",
    }
    (output / "wheelhouse_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wheelhouse完成：{output}，wheel数量={len(wheels)}")
    print("该目录只有在机房兼容环境完成离线安装试跑后，才能作为冻结环境包使用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
