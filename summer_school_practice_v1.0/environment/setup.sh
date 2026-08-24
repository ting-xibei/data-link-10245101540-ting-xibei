#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_COMMAND="${PYTHON_COMMAND:-python3}"

"$PYTHON_COMMAND" -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"$PROJECT_ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -r "$PROJECT_ROOT/environment/requirements.txt"
if [[ -d "$PROJECT_ROOT/ta_reference_package" ]]; then
    CHECK_SCRIPT="$PROJECT_ROOT/environment/run_all_checks.py"
else
    CHECK_SCRIPT="$PROJECT_ROOT/environment/run_student_checks.py"
fi
"$PROJECT_ROOT/.venv/bin/python" "$CHECK_SCRIPT"
