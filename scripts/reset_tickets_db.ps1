param(
    [string]$ApiComposeFile = "docker/docker-compose.api.snippet.yml",
    [string]$KafkaComposeFile = "docker/docker-compose.kafka.yml",
    [string]$ServiceName = "dashboard-api",
    [string]$VolumeNameHint = "tickets_db",
    [switch]$NoRebuild,
    [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"

Write-Host "== Reset Tickets DB (Docker volume) ==" -ForegroundColor Cyan
function Resolve-PathIfRelative {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Base
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return $Path }
    if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
    return (Join-Path $Base $Path)
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$ApiComposeFileResolved = Resolve-PathIfRelative -Path $ApiComposeFile -Base $RepoRoot
$KafkaComposeFileResolved = Resolve-PathIfRelative -Path $KafkaComposeFile -Base $RepoRoot

Write-Host "Repo root:     $RepoRoot"
Write-Host "Api compose:   $ApiComposeFileResolved"
Write-Host "Kafka compose: $KafkaComposeFileResolved"
Write-Host "Service:       $ServiceName"
Write-Host "Volume hint:   $VolumeNameHint"
Write-Host ""

function Get-ComposeArgs {
    @("-f", $KafkaComposeFileResolved, "-f", $ApiComposeFileResolved)
}

$composeArgs = Get-ComposeArgs

if (-not (Test-Path $KafkaComposeFileResolved)) {
    throw "Kafka compose file not found: $KafkaComposeFileResolved (current dir: $PWD)"
}
if (-not (Test-Path $ApiComposeFileResolved)) {
    throw "API compose file not found: $ApiComposeFileResolved (current dir: $PWD)"
}

# Ensure Docker Compose uses the intended project name/context (defaults to current directory name).
Push-Location $RepoRoot
try {

    if (-not $SkipRestart) {
        Write-Host "Stopping service: $ServiceName" -ForegroundColor Yellow
        docker compose @composeArgs stop $ServiceName | Out-String | Write-Host

        Write-Host "Removing service container: $ServiceName" -ForegroundColor Yellow
        docker compose @composeArgs rm -f $ServiceName | Out-String | Write-Host
    }

    Write-Host "Searching for volumes matching '$VolumeNameHint'..." -ForegroundColor Yellow
    $vols = docker volume ls --format "{{.Name}}" | Where-Object {
        $_ -eq $VolumeNameHint -or $_ -like "*_${VolumeNameHint}" -or $_ -like "${VolumeNameHint}_*" -or $_ -like "*${VolumeNameHint}*"
    } | Sort-Object -Unique

    if (-not $vols -or $vols.Count -eq 0) {
        Write-Host "No volumes matched. Nothing to delete." -ForegroundColor Gray
    } else {
        Write-Host "Deleting volumes:" -ForegroundColor Yellow
        $vols | ForEach-Object { Write-Host " - $_" }
        $vols | ForEach-Object {
            try {
                docker volume rm $_ | Out-String | Write-Host
            } catch {
                Write-Host "Failed to remove volume '$_': $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }

    if (-not $SkipRestart) {
        Write-Host "Starting service: $ServiceName" -ForegroundColor Yellow
        if ($NoRebuild) {
            docker compose @composeArgs up -d $ServiceName | Out-String | Write-Host
        } else {
            docker compose @composeArgs up -d --build $ServiceName | Out-String | Write-Host
        }

        Write-Host "Waiting for API health..." -ForegroundColor Yellow
        Start-Sleep -Seconds 2

        try {
            $health = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -TimeoutSec 5
            Write-Host "API health OK: $($health | ConvertTo-Json -Depth 4)" -ForegroundColor Green
        } catch {
            Write-Host "API health check failed (may still be starting): $($_.Exception.Message)" -ForegroundColor Yellow
        }

        try {
            $metrics = Invoke-RestMethod -Uri "http://localhost:8000/api/tickets/metrics" -TimeoutSec 5
            Write-Host "Tickets metrics: $($metrics | ConvertTo-Json -Depth 4)" -ForegroundColor Green
        } catch {
            Write-Host "Tickets metrics check failed: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    Write-Host "Done." -ForegroundColor Cyan
} finally {
    Pop-Location
}
