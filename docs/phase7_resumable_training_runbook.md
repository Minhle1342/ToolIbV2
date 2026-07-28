# Phase 7 - Resumable Colab training

Phase 7 protects a long training run from a lost Colab runtime. The worker
uploads `last.pt` to S3-compatible object storage every five epochs. ToolIb
waits 120 seconds for the original worker to reconnect. If it does not return,
the scheduler sends the newest verified checkpoint to another compatible
worker and continues the remaining epochs.

The existing training flow remains available when object storage is disabled.
Cross-worker resume is enabled only when ToolIb has object-storage
configuration and the registered worker reports the Phase 7 capabilities.

## 1. Create the R2 resources

1. In Cloudflare, open **R2 Object Storage**.
2. Create a Standard storage bucket, for example `toolib-training`.
3. Create an R2 API token scoped to read and write objects in only that bucket.
4. Copy the Access Key ID and Secret Access Key once. Do not put either key in
   Colab Secrets or in the notebook.
5. Copy the account-specific S3 endpoint:
   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

R2 documentation:

- https://developers.cloudflare.com/r2/api/s3/tokens/
- https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- https://developers.cloudflare.com/r2/pricing/

## 2. Configure ToolIb on the Windows machine

Create this local-only file in the repository root:

```text
.env.object-storage.local
```

Paste the following values without quotes:

```dotenv
TOOLIB_OBJECT_STORE_BACKEND=s3
TOOLIB_OBJECT_STORE_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
TOOLIB_OBJECT_STORE_REGION=auto
TOOLIB_OBJECT_STORE_BUCKET=toolib-training
TOOLIB_OBJECT_STORE_ACCESS_KEY_ID=<R2_ACCESS_KEY_ID>
TOOLIB_OBJECT_STORE_SECRET_ACCESS_KEY=<R2_SECRET_ACCESS_KEY>
TOOLIB_OBJECT_STORE_PREFIX=toolib
TOOLIB_OBJECT_STORE_PRESIGN_SECONDS=604800
```

The `.env.object-storage.local` file is ignored by Git. `run.ps1` loads it
only into the ToolIb processes. The keys never enter the training request.
Colab receives short-lived, object-scoped presigned URLs.

## 3. Start ToolIb and verify the schema

Run:

```powershell
.\run.ps1
```

When the S3 backend is enabled, the launcher installs `boto3` if the existing
virtual environment does not already contain it.

In another PowerShell window, optionally verify the additive migration:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_phase7_resumable_training.py --check
```

Expected output:

```text
Phase 7 schema ready (20260728_phase7_resumable_training).
```

## 4. Replace the notebook on every Colab account

Upload and run this notebook on every Colab account:

```text
notebooks/Colab_FastAPI_PoC.ipynb
```

An older Phase 6 worker can still train normally but cannot receive a
cross-worker resume task. After registering or probing the worker, its health
capabilities must include:

```json
{
  "checkpoint_upload": true,
  "checkpoint_resume": true,
  "checkpoint_protocol_version": 1
}
```

## 5. Controlled failover smoke test

Use two registered Colab workers and queue one small job:

- epochs: `10`
- checkpoint interval: default `5`
- maximum resume count: default `3`

The expected sequence is:

```text
worker A: remote_running
worker A: checkpoint epoch 5/10 uploaded
worker A disconnects
task: worker_lost
120-second reconnect grace expires
task: resume_pending
worker B: remote_running, resume from epoch 5
worker B: checkpoint epoch 10/10 uploaded
task: downloading_artifacts
task: importing_model
task: succeeded
```

To simulate the failure, wait until the manager displays `Checkpoint epoch
5/10`, then disconnect worker A's Colab runtime. Keep worker B online. Do not
press Retry; the scheduler performs the failover automatically.

The batch card displays:

- checkpoint epoch and size;
- recovery generation;
- current resume count;
- whether the latest attempt is `initial` or `resume`;
- the epoch from which a resume attempt started.

## Acceptance criteria

The Phase 7 smoke test passes when:

1. R2 contains a checkpoint object under the task-scoped prefix.
2. Worker A is marked lost and is given the reconnect grace period.
3. Worker B receives `execution_mode=resume`.
4. Worker B downloads a checkpoint whose size and SHA-256 match the database.
5. The resumed attempt uses a newer recovery generation.
6. A late result from the older generation cannot import or activate a model.
7. The final model is imported exactly once.
8. At most the newest two verified checkpoint objects remain for the task.

## Operational notes

- `last.pt` is the resumable training state. `best.pt` remains the best model
  candidate, and `best.onnx` remains the inference artifact.
- A disconnect before the first checkpoint cannot move to another worker.
  ToolIb keeps waiting for the original worker because there is no safe state
  from which to resume.
- Presigned URLs expire after the configured lifetime. The default is seven
  days so a long Colab training job does not lose its later upload targets.
- Revoking or rotating the R2 token requires restarting `run.ps1`.
