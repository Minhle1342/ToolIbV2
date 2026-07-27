# PostgreSQL control-plane runbook

## Goal

Run the Flask process and training scheduler against one PostgreSQL database.
SQLite remains a local fallback, but it is not the production control-plane
database.

## Local migration

Stop `run.ps1`, then run:

```powershell
.\scripts\setup_postgres.ps1
```

The script:

1. Generates `.env.postgres.local` with a random local password.
2. Starts `toolib_postgres` through Docker Compose.
3. Backs up `yolo_labeling.db` under `backups/`.
4. Copies all ToolIb tables into an empty PostgreSQL database.
5. Repairs only nullable orphan foreign keys during the copy.
6. Verifies every copied table row count.
7. Starts the application once against PostgreSQL as a smoke check.

After it succeeds, start ToolIb normally:

```powershell
.\run.ps1
```

`run.ps1` loads `.env.postgres.local` automatically. The secret file and
database backups are ignored by Git.

## Rollback

1. Stop `run.ps1`.
2. Rename `.env.postgres.local` so `run.ps1` cannot load it.
3. Start `run.ps1`; the application returns to `yolo_labeling.db`.

The migration never modifies the source SQLite database.

## Production configuration

Set these values through the deployment secret manager:

```text
YOLO_LABELING_DB_URI=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
TOOLIB_WORKER_CREDENTIAL_KEY=<stable-fernet-key>
TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY=true
```

Do not use the local Docker password or commit `.env.postgres.local`.

## Remote-job recovery

If a remote worker accepted a job but local synchronization was interrupted,
adopt it without retraining:

```http
POST /api/training-queue-tasks/<task-id>/adopt
Content-Type: application/json

{
  "worker_id": 1,
  "remote_job_id": "00000000-0000-0000-0000-000000000000"
}
```

The scheduler resumes status polling, downloads the existing ONNX artifact and
imports it as an inactive model.
