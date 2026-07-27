param(
    [switch]$SkipMigration
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$environmentPath = Join-Path $repositoryRoot '.env.postgres.local'
$composePath = Join-Path $repositoryRoot 'compose.postgres.yml'
$databasePath = Join-Path $repositoryRoot 'yolo_labeling.db'
$pythonPath = Join-Path $repositoryRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv. Run run.ps1 once to create the Python environment.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop is required for the local PostgreSQL service.'
}

if (-not (Test-Path -LiteralPath $environmentPath)) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $passwordBytes = New-Object byte[] 32
        $rng.GetBytes($passwordBytes)
        $password = -join ($passwordBytes | ForEach-Object { $_.ToString('x2') })
    } finally {
        $rng.Dispose()
    }
    @(
        'TOOLIB_POSTGRES_DB=toolib'
        'TOOLIB_POSTGRES_USER=toolib'
        "TOOLIB_POSTGRES_PASSWORD=$password"
        'TOOLIB_POSTGRES_PORT=54329'
        "YOLO_LABELING_DB_URI=postgresql+psycopg://toolib:$password@127.0.0.1:54329/toolib"
    ) | Set-Content -LiteralPath $environmentPath -Encoding ASCII
    Write-Host "[DATABASE] Created local secret file .env.postgres.local." -ForegroundColor Green
}

$settings = @{}
foreach ($line in Get-Content -LiteralPath $environmentPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) {
        continue
    }
    $name, $value = $trimmed -split '=', 2
    $settings[$name] = $value
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
}

& docker compose --env-file $environmentPath -f $composePath up -d
if ($LASTEXITCODE -ne 0) {
    throw 'Could not start the ToolIb PostgreSQL container.'
}

$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    $health = & docker inspect --format '{{.State.Health.Status}}' toolib_postgres 2>$null
    if ($health -eq 'healthy') {
        $healthy = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    throw 'PostgreSQL did not become healthy within 60 seconds.'
}
Write-Host "[DATABASE] PostgreSQL is healthy on 127.0.0.1:$($settings['TOOLIB_POSTGRES_PORT'])." -ForegroundColor Green

& $pythonPath -m pip install -r (Join-Path $repositoryRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw 'Could not install the PostgreSQL Python driver.'
}

if (-not $SkipMigration) {
    if (-not (Test-Path -LiteralPath $databasePath)) {
        throw 'Source yolo_labeling.db was not found.'
    }
    $backupRoot = Join-Path $repositoryRoot 'backups'
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupPath = Join-Path $backupRoot "yolo_labeling-before-postgres-$timestamp.db"
    Copy-Item -LiteralPath $databasePath -Destination $backupPath
    Write-Host "[DATABASE] SQLite backup: $backupPath" -ForegroundColor Green

    $sourceUri = 'sqlite:///' + ($databasePath -replace '\\', '/')
    & $pythonPath (Join-Path $repositoryRoot 'scripts\migrate_sqlite_to_postgres.py') `
        --source-uri $sourceUri `
        --target-uri $settings['YOLO_LABELING_DB_URI']
    if ($LASTEXITCODE -ne 0) {
        throw 'SQLite to PostgreSQL migration failed. SQLite remains unchanged.'
    }
}

& $pythonPath -c "from app import create_app; app=create_app(); print(app.config['SQLALCHEMY_DATABASE_URI'].split('@')[-1])"
if ($LASTEXITCODE -ne 0) {
    throw 'PostgreSQL application startup verification failed.'
}

Write-Host ''
Write-Host '[DONE] PostgreSQL is ready. Restart run.ps1 to use it.' -ForegroundColor Green
