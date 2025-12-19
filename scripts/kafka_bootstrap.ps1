<#
Kafka bootstrap helper for local development.

What it does:
    1) Starts Kafka + Kafka UI via docker compose
    2) Waits until the broker responds
    3) Creates the telemetry topic (idempotent)

Run (from anywhere):
    powershell -ExecutionPolicy Bypass -File E:\dissertation-project\agentic-fault-gpt\scripts\kafka_bootstrap.ps1

Run (from repo root):
    .\scripts\kafka_bootstrap.ps1

Options:
    .\scripts\kafka_bootstrap.ps1 -Topic ahu.telemetry -MaxWaitSeconds 120 -PollSeconds 2

Notes:
    - This script assumes the broker container name is "afg-kafka".
    - If you change KRaft cluster settings (cluster id / quorum init) and Kafka won't start,
      you may need to wipe the Kafka data volume:
          docker compose -f docker/docker-compose.kafka.yml down -v
#>

[CmdletBinding()]
param(
    [string]$ComposeFile = "docker/docker-compose.kafka.yml",
    [string]$KafkaContainerName = "afg-kafka",
    [string]$Topic = "ahu.telemetry",
    [int]$Partitions = 1,
    [int]$ReplicationFactor = 1,
    [int]$MaxWaitSeconds = 60,
    [int]$PollSeconds = 3
)

$ErrorActionPreference = "Stop"

function Assert-DockerAvailable {
    try {
        & docker version | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "docker version returned non-zero exit code." }
    } catch {
        throw "Docker does not appear to be available. Is Docker Desktop running? Original error: $($_.Exception.Message)"
    }
}

function Resolve-ComposePath([string]$composeFile) {
    # Resolve repo root from this script's location so relative paths work
    $repoRoot = (Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).Path

    if ([System.IO.Path]::IsPathRooted($composeFile)) {
        return $composeFile
    }

    return (Join-Path -Path $repoRoot -ChildPath $composeFile)
}

function Assert-ContainerExists([string]$containerName) {
    $names = & docker ps -a --format "{{.Names}}"
    if ($LASTEXITCODE -ne 0) { throw "Failed to list docker containers." }

    $found = $false
    foreach ($n in $names) {
        if ($n -eq $containerName) { $found = $true; break }
    }
    if (-not $found) {
        throw "Kafka container not found: '$containerName'. Did docker compose start it?"
    }
}

function Wait-ForKafkaReady([string]$containerName, [int]$maxWaitSeconds, [int]$pollSeconds) {
    Write-Host "Waiting for Kafka to be ready (max ${maxWaitSeconds}s)..."
    $elapsed = 0

    while ($true) {
        # Use kafka-broker-api-versions to check readiness (works without a topic)
        & docker exec -i $containerName bash -lc "/opt/bitnami/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server kafka:29092" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return
        }

        if ($elapsed -ge $maxWaitSeconds) {
            throw "Kafka did not become ready within $maxWaitSeconds seconds (container: $containerName)."
        }

        Start-Sleep -Seconds $pollSeconds
        $elapsed += $pollSeconds
    }
}

function Create-Topic([string]$containerName, [string]$topic, [int]$partitions, [int]$replicationFactor) {
    Write-Host "Creating Kafka topic (idempotent): $topic"
    $cmd = "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --create --if-not-exists --topic '$topic' --partitions $partitions --replication-factor $replicationFactor"
    & docker exec -i $containerName bash -lc $cmd
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create topic '$topic'."
    }
}

# --- Main ---

Assert-DockerAvailable

$composePath = Resolve-ComposePath $ComposeFile
if (-not (Test-Path -LiteralPath $composePath)) {
    throw "Compose file not found: $composePath"
}

Write-Host "Starting Kafka via Docker Compose..."
& docker compose -f $composePath up -d
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed. Check the compose file and docker daemon."
}

Assert-ContainerExists $KafkaContainerName
Wait-ForKafkaReady -containerName $KafkaContainerName -maxWaitSeconds $MaxWaitSeconds -pollSeconds $PollSeconds
Create-Topic -containerName $KafkaContainerName -topic $Topic -partitions $Partitions -replicationFactor $ReplicationFactor

Write-Host "Kafka is ready."
Write-Host "You can now run producer or consumer in any order."

Write-Host "Kafka bootstrap complete."
Write-Host "Host clients should use: localhost:9092"
Write-Host "Container clients should use: kafka:29092"
