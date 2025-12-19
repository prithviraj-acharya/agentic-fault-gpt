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

# Resolve repo root from this script's location so relative paths work
$RepoRoot = (Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath "..") ).Path
$ComposePath = if ([System.IO.Path]::IsPathRooted($ComposeFile)) {
    $ComposeFile
} else {
    (Join-Path -Path $RepoRoot -ChildPath $ComposeFile)
}

if (-not (Test-Path -LiteralPath $ComposePath)) {
    throw "Compose file not found: $ComposePath"
}

Write-Host "Starting Kafka via Docker Compose..."
& docker compose -f $ComposePath up -d

Write-Host "Waiting for Kafka to be ready..."
$elapsed = 0
while ($true) {
    try {
        & docker exec -i $KafkaContainerName bash -lc "/opt/bitnami/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server kafka:29092" | Out-Null
        break
    } catch {
        if ($elapsed -ge $MaxWaitSeconds) {
            throw "Kafka did not become ready within $MaxWaitSeconds seconds (container: $KafkaContainerName)."
        }
        Start-Sleep -Seconds $PollSeconds
        $elapsed += $PollSeconds
    }
}

Write-Host "Creating Kafka topic (idempotent)..."
& docker exec -i $KafkaContainerName bash -lc "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --create --if-not-exists --topic '$Topic' --partitions $Partitions --replication-factor $ReplicationFactor"

Write-Host "Kafka is ready."
Write-Host "You can now run producer or consumer in any order."
