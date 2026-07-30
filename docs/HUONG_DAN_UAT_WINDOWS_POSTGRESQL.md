# Huong dan UAT ToolIbV2 tren Windows va Docker Desktop

Tai lieu nay danh cho may UAT Windows moi, da co WSL2 va Docker Desktop.
Tat ca lenh trong tai lieu duoc chay bang **Windows PowerShell**. Khong mo Ubuntu
va khong chay `sudo`. Docker Desktop co the su dung WSL2 o ben duoi, nhung Flask,
scheduler, Python va cac migration deu chay truc tiep tren Windows.

Quy trinh nay tao mot PostgreSQL UAT trong. Khong copy database hoac secret tu
DEV va khong dung quy trinh nay de ghi de database production.

## 1. Runtime map

```text
Windows
|- Docker Desktop
|  `- toolib_postgres: PostgreSQL 17, 127.0.0.1:54329
|- Python 3.11 virtual environment: .venv\Scripts\python.exe
|- Flask HTTPS: https://localhost:5000
`- training_scheduler.py
```

WSL2 chi la Docker Desktop backend. PostgreSQL chi bind vao `127.0.0.1`, khong
mo port `54329` ra LAN.

## 2. Mo Windows PowerShell

Mo **Windows PowerShell** hoac **PowerShell 7**. Khong mo terminal Ubuntu/WSL.

Cho phep chay script trong cua so hien tai:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

Kiem tra Docker Desktop da khoi dong:

```powershell
docker version
docker compose version
docker info
```

Dung lai neu Docker CLI khong ket noi duoc Docker Desktop.

## 3. Cai Git va Python 3.11

Kiem tra truoc:

```powershell
git --version
py -3.11 --version
```

Neu thieu Git hoac Python 3.11, cai bang `winget`:

```powershell
winget install --exact --id Git.Git
winget install --exact --id Python.Python.3.11
```

Sau khi cai moi, dong PowerShell, mo lai mot cua so PowerShell moi va chay lai:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
git --version
py -3.11 --version
```

## 4. Clone dung ban UAT

```powershell
Set-Location $HOME

git clone https://github.com/Minhle1342/ToolIbV2.git
Set-Location .\ToolIbV2

git status
git log -1 --oneline
```

Commit phai bang commit moi nhat tren `origin/main`.

## 5. Tao Python virtual environment

```powershell
Set-Location $HOME\ToolIbV2

py -3.11 -m venv .venv

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

& .\.venv\Scripts\python.exe --version
& .\.venv\Scripts\python.exe -c "import flask, sqlalchemy, psycopg, cv2; print('PYTHON READY')"
```

Python phai la `3.11.x` va lenh cuoi phai in `PYTHON READY`.

## 6. Tao PostgreSQL UAT moi

Lenh sau tao `.env.postgres.local`, tao PostgreSQL container va khong import
SQLite DEV:

```powershell
Set-Location $HOME\ToolIbV2
Set-ExecutionPolicy -Scope Process Bypass -Force

& .\scripts\setup_postgres.ps1 -SkipMigration
```

Phai thay thong bao:

```text
[DATABASE] PostgreSQL is healthy on 127.0.0.1:54329.
[DONE] PostgreSQL is ready.
```

`-SkipMigration` la bat buoc cho may UAT moi. Khong chay script khong co tham so
nay, vi luong mac dinh dung de copy file `yolo_labeling.db` hien co sang
PostgreSQL.

## 7. Them key bao mat cua Colab worker

`setup_postgres.ps1` tao database password. Khoi sau them Fernet key rieng cho
may UAT va thu muc artifact tren Windows:

```powershell
Set-Location $HOME\ToolIbV2

$pythonPath = Join-Path $PWD '.venv\Scripts\python.exe'
$environmentPath = Join-Path $PWD '.env.postgres.local'
$artifactRoot = Join-Path $HOME 'ToolIbV2-UAT\model_artifacts'
$workerKey = & $pythonPath -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null

$managedNames = @(
    'TOOLIB_WORKER_CREDENTIAL_KEY',
    'TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY',
    'TOOLIB_FINETUNE_ENABLED',
    'TOOLIB_MODEL_ARTIFACT_ROOT'
)

$existingLines = Get-Content -LiteralPath $environmentPath | Where-Object {
    $line = $_
    -not ($managedNames | Where-Object { $line -like "$_=*" })
}

$newLines = @(
    "TOOLIB_WORKER_CREDENTIAL_KEY=$workerKey",
    'TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY=true',
    'TOOLIB_FINETUNE_ENABLED=true',
    "TOOLIB_MODEL_ARTIFACT_ROOT=$artifactRoot"
)

@($existingLines) + $newLines |
    Set-Content -LiteralPath $environmentPath -Encoding ASCII

Remove-Variable workerKey
```

Khong commit, gui hoac chup man hinh noi dung `.env.postgres.local`.

## 8. Nap environment vao PowerShell hien tai

Chay khoi nay truoc migration, preflight hoac lenh Python thu cong:

```powershell
Set-Location $HOME\ToolIbV2

Get-Content -LiteralPath .\.env.postgres.local | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        $name, $value = $line -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

& .\.venv\Scripts\python.exe -c "import os; print(os.environ['YOLO_LABELING_DB_URI'].split('@')[-1])"
```

Ket qua phai la:

```text
127.0.0.1:54329/toolib
```

## 9. Tao schema va migration ledger

Chay trong cung cua so PowerShell da nap environment:

```powershell
$pythonPath = Join-Path $PWD '.venv\Scripts\python.exe'

& $pythonPath -c "from app import create_app; create_app(); print('DATABASE SCHEMA READY')"

& $pythonPath .\scripts\migrate_phase5_control_plane.py
& $pythonPath .\scripts\migrate_phase6_finetune.py
& $pythonPath .\scripts\migrate_phase7_resumable_training.py
& $pythonPath .\scripts\migrate_phase8_object_transport.py
& $pythonPath .\scripts\migrate_phase9_optimizer_contract.py
```

Kiem tra read-only:

```powershell
& $pythonPath .\scripts\migrate_phase5_control_plane.py --check
& $pythonPath .\scripts\migrate_phase6_finetune.py --check
& $pythonPath .\scripts\migrate_phase7_resumable_training.py --check
& $pythonPath .\scripts\migrate_phase8_object_transport.py --check
& $pythonPath .\scripts\migrate_phase9_optimizer_contract.py --status

& $pythonPath .\scripts\training_preflight.py `
    --database-uri $env:YOLO_LABELING_DB_URI
```

Preflight chua co worker URL co the bao `worker-health: SKIP`. Catalog,
notebook va database checks phai `PASS`; tong ket non-strict phai la `READY`.

Xem cac table PostgreSQL:

```powershell
docker exec toolib_postgres sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
```

Can thay toi thieu:

- `projects`, `images`, `ai_models`;
- `training_workers`, `training_batches`, `training_queue_tasks`;
- `fine_tune_parameter_sets`, `toolib_schema_migrations`.

## 10. Khoi dong ToolIbV2

Mo mot cua so PowerShell tai repo va chay:

```powershell
Set-Location $HOME\ToolIbV2
Set-ExecutionPolicy -Scope Process Bypass -Force

& .\run.ps1
```

`run.ps1` tu dong:

- nap `.env.postgres.local`;
- kiem tra/cai dependency;
- kiem tra database schema;
- khoi dong `training_scheduler.py` an trong nen;
- chay Flask HTTPS;
- mo `https://localhost:5000`.

Giu cua so PowerShell nay dang mo. Bam `Ctrl+C` se dung Flask va scheduler do
`run.ps1` khoi dong.

## 11. Smoke test Windows UAT

Mo cua so PowerShell thu hai:

```powershell
Set-Location $HOME\ToolIbV2
$pythonPath = Join-Path $PWD '.venv\Scripts\python.exe'

curl.exe -k -I https://127.0.0.1:5000/

$statusJson = curl.exe -ks https://127.0.0.1:5000/api/training-control-plane/status
$statusJson | & $pythonPath -m json.tool

$catalogJson = curl.exe -ks https://127.0.0.1:5000/api/training-model-catalog
$catalogJson | & $pythonPath -m json.tool
```

Tren browser:

1. Mo `https://localhost:5000/colab-manager`.
2. Kiem tra banner `Tai nguyen huan luyen`.
3. Kiem tra co YOLO11, YOLO12 va YOLO26.
4. Bam `Dang ky Colab`.
5. Nhap URL, bearer token va ten may Colab.
6. Bam `Kiem tra ket noi`; worker phai chuyen sang online.

Sau khi co worker URL, chay strict preflight. Lenh `Read-Host` khong ghi token
vao PowerShell command history:

```powershell
Get-Content -LiteralPath .\.env.postgres.local | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        $name, $value = $line -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

$env:TOOLIB_COLAB_API_TOKEN = Read-Host 'Nhap worker bearer token'

& $pythonPath .\scripts\training_preflight.py `
    --database-uri $env:YOLO_LABELING_DB_URI `
    --worker-url 'https://your-worker.trycloudflare.com' `
    --strict

Remove-Item Env:TOOLIB_COLAB_API_TOKEN
```

## 12. Backup PostgreSQL UAT

Khong redirect binary `pg_dump` truc tiep bang Windows PowerShell. Tao file
trong container roi copy ra Windows:

```powershell
$backupRoot = Join-Path $HOME 'ToolIbV2-UAT\backups'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = Join-Path $backupRoot "toolib-$timestamp.dump"

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

docker exec toolib_postgres sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/toolib-uat.dump'
docker cp toolib_postgres:/tmp/toolib-uat.dump $backupPath
docker exec toolib_postgres rm -f /tmp/toolib-uat.dump

Get-Item -LiteralPath $backupPath | Select-Object FullName, Length, LastWriteTime
```

`docker compose down` giu volume. Khong chay lenh sau neu khong chu dong xoa
toan bo database UAT:

```powershell
docker compose --env-file .env.postgres.local -f compose.postgres.yml down -v
```

## 13. Truy cap tu may khac trong LAN

Tren chinh may UAT, dung:

```text
https://localhost:5000
```

De may khac trong LAN truy cap, can mo Windows Firewall TCP `5000`. Chay trong
PowerShell **Run as administrator** neu thuc su can:

```powershell
New-NetFirewallRule `
    -DisplayName 'ToolIbV2 UAT HTTPS 5000' `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 5000 `
    -Action Allow
```

Sau do truy cap `https://<IP-WINDOWS-UAT>:5000`. Khong mo PostgreSQL port
`54329` ra LAN.

## 14. Ket qua can gui lai de kiem tra

Chay trong PowerShell:

```powershell
Set-Location $HOME\ToolIbV2

Get-Content -LiteralPath .\.env.postgres.local | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        $name, $value = $line -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

$pythonPath = Join-Path $PWD '.venv\Scripts\python.exe'

git log -1 --oneline
docker compose --env-file .env.postgres.local -f compose.postgres.yml ps
docker inspect --format '{{.State.Health.Status}}' toolib_postgres
& $pythonPath .\scripts\migrate_phase9_optimizer_contract.py --status
& $pythonPath .\scripts\training_preflight.py --database-uri $env:YOLO_LABELING_DB_URI
```

Khong gui `.env.postgres.local`, database password, worker bearer token hoac
`TOOLIB_WORKER_CREDENTIAL_KEY`.
