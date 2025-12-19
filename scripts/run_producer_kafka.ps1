<#
Run the telemetry producer in Kafka mode (with defaults).

Run (from repo root):
    .\scripts\run_producer_kafka.ps1

Run (from anywhere):
    powershell -ExecutionPolicy Bypass -File E:\dissertation-project\agentic-fault-gpt\scripts\run_producer_kafka.ps1

Examples:
    .\scripts\run_producer_kafka.ps1
    .\scripts\run_producer_kafka.ps1 -MaxEvents 5
    .\scripts\run_producer_kafka.ps1 -ScenarioFile simulation/scenarios/scenario_v1.json -Topic ahu.telemetry
#>

[CmdletBinding()]
param(
    [string]$ScenarioFile = "simulation/scenarios/scenario_v1.json",
    [string]$BootstrapServers = "localhost:9092",
    [string]$Topic = "ahu.telemetry",
    [double]$Speed = 0,
    [string]$OutDir = "data/generated",
    [int]$MaxEvents = 0,
    [switch]$EnsureKafka
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath "..") ).Path
}

function Get-PythonExe([string]$repoRoot) {
    $candidates = @(
        (Join-Path -Path $repoRoot -ChildPath ".venv\Scripts\python.exe"),
        (Join-Path -Path $repoRoot -ChildPath "venv\Scripts\python.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path -LiteralPath $p) { return $p }
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return "python" }

    throw "Could not find Python. Create/activate a venv or install Python." 
}

$repoRoot = Get-RepoRoot
$pythonExe = Get-PythonExe -repoRoot $repoRoot

$scenarioPath = if ([System.IO.Path]::IsPathRooted($ScenarioFile)) { $ScenarioFile } else { Join-Path -Path $repoRoot -ChildPath $ScenarioFile }
if (-not (Test-Path -LiteralPath $scenarioPath)) {
    throw "Scenario file not found: $scenarioPath"
}

$outPath = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path -Path $repoRoot -ChildPath $OutDir }
if (-not (Test-Path -LiteralPath $outPath)) { New-Item -ItemType Directory -Path $outPath | Out-Null }

if ($EnsureKafka) {
    $bootstrapScript = Join-Path -Path $repoRoot -ChildPath "scripts\kafka_bootstrap.ps1"
    if (-not (Test-Path -LiteralPath $bootstrapScript)) {
        throw "Kafka bootstrap script not found: $bootstrapScript"
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $bootstrapScript | Out-Host
}

Write-Host "Running producer (Kafka mode)..." -ForegroundColor Cyan
Write-Host "  Scenario:  $scenarioPath" -ForegroundColor DarkGray
Write-Host "  Bootstrap: $BootstrapServers" -ForegroundColor DarkGray
Write-Host "  Topic:     $Topic" -ForegroundColor DarkGray
Write-Host "  Speed:     $Speed" -ForegroundColor DarkGray
Write-Host "  OutDir:    $outPath" -ForegroundColor DarkGray
Write-Host "  MaxEvents: $MaxEvents" -ForegroundColor DarkGray

Push-Location -LiteralPath $repoRoot
try {
    if ($pythonExe -eq "python") {
        & python -m simulation.producer --scenario "$scenarioPath" --mode kafka --bootstrap-servers "$BootstrapServers" --topic "$Topic" --speed $Speed --out "$outPath" --max-events $MaxEvents
    } else {
        & $pythonExe -m simulation.producer --scenario "$scenarioPath" --mode kafka --bootstrap-servers "$BootstrapServers" --topic "$Topic" --speed $Speed --out "$outPath" --max-events $MaxEvents
    }
} finally {
    Pop-Location
}
