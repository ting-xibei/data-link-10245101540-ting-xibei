param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvRoot = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"

function Assert-LastExitCode {
    param([string]$StepName)
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

Write-Host "[1/4] Creating virtual environment: $VenvRoot"
& $PythonCommand -m venv $VenvRoot
Assert-LastExitCode "Virtual environment creation"

Write-Host "[2/4] Updating pip"
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
Assert-LastExitCode "pip upgrade"

Write-Host "[3/4] Installing required packages"
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements.txt")
Assert-LastExitCode "Dependency installation"

if (Test-Path (Join-Path $ProjectRoot "ta_reference_package")) {
    $CheckScript = Join-Path $PSScriptRoot "run_all_checks.py"
    $CheckCommand = ".\.venv\Scripts\python.exe environment\run_all_checks.py"
} else {
    $CheckScript = Join-Path $PSScriptRoot "run_student_checks.py"
    $CheckCommand = ".\.venv\Scripts\python.exe environment\run_student_checks.py"
}

Write-Host "[4/4] Running environment and practice-package checks"
& $VenvPython $CheckScript
Assert-LastExitCode "Project checks"

Write-Host "Setup complete. Re-run with: $CheckCommand"
