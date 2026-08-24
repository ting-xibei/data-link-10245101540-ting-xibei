from __future__ import annotations

from pathlib import Path


STUDENT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = STUDENT_PACKAGE_ROOT / "output"


def prepare_output_directory() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def parse() -> None:
    raise NotImplementedError("TODO：接入M2 OpenSky解析实现，并输出结构化解析结果。")


def encode() -> None:
    raise NotImplementedError("TODO：接入M2 TeachingLink编码实现。")


def decode_validate() -> None:
    raise NotImplementedError("TODO：接入M2解码与帧验证实现。")


def build_tracks() -> None:
    raise NotImplementedError("TODO：接入M3航迹与当前态势实现。")


def map_unified() -> None:
    raise NotImplementedError("TODO：接入M4人工核验后的映射实现。")


def check_quality() -> None:
    raise NotImplementedError("TODO：接入M5一致性检查实现。")


def export_results() -> None:
    raise NotImplementedError("TODO：整理M6关键成果和README；不得把助教检查点当成本模块成果。")


def run_pipeline() -> None:
    prepare_output_directory()
    parse()
    encode()
    decode_validate()
    build_tracks()
    map_unified()
    check_quality()
    export_results()


def main() -> int:
    try:
        run_pipeline()
    except NotImplementedError as exc:
        print(exc)
        print("当前文件是学生骨架，模块实现完成后再进行端到端运行。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
