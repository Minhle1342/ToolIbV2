# Phase 5 — Production-grade Training Control Plane

## 1. Objective

Turn the verified Phase 4 single-Colab flow into a durable, provider-neutral
control plane that can run many training jobs across many GPU workers.

Colab is the first `http_push` worker provider. The control plane must not
depend on Google account, Google Drive, or Cloudflare-specific behavior so a
future local/GCP/AWS worker can implement the same contract.

## 2. Phase boundary

### Automated after a worker is registered

1. Create an immutable dataset snapshot.
2. Verify the snapshot checksum.
3. Select an online compatible worker.
4. Upload or reuse the snapshot on that worker.
5. Submit an idempotent training request.
6. Poll and persist progress.
7. Download and centrally store artifacts.
8. Import ONNX as an inactive ToolIbV2 model.
9. Release the worker and dispatch the next queued job.
10. Retry recoverable failures without duplicating remote jobs or models.

### Colab-only manual boundary

The user still starts the managed Colab runtime and authorizes Google Drive.
Everything after worker registration is controlled by ToolIbV2. A future
provider adapter may automate provisioning as well.

## 3. Runtime flow

```text
Training batch
  -> durable queue task
  -> scheduler lease
  -> worker adapter
  -> immutable dataset snapshot/upload
  -> remote training job
  -> remote progress synchronization
  -> central artifact storage
  -> inactive model import
  -> task and batch completion
```

## 4. Persistent data model

### `training_workers`

- Stable UUID, display name and provider.
- Normalized API origin and encrypted bearer token.
- Status, GPU/capability snapshot, capacity and heartbeat timestamps.
- No secret value is returned by any API.

### `training_batches`

- Stable UUID and user-facing name.
- Aggregate status and timestamps.
- Owns multiple queue tasks.

### `training_queue_tasks`

- Stable UUID and unique idempotency key.
- Batch, project, dataset snapshot, remote history and imported model links.
- Requested model/hyperparameters and dataset selection options.
- Durable state machine, retry counters, lease and timestamps.

### `training_job_attempts`

- One row per assignment/retry.
- Worker, attempt number, lease token, remote job ID and error.
- Allows reconnect and audit without overwriting previous attempts.

### `training_job_events`

- Append-only status/event timeline.
- Contains stage, message and safe structured details.

## 5. State machine

```text
queued
  -> preparing_dataset
  -> waiting_for_worker
  -> uploading_dataset
  -> submitting
  -> remote_queued
  -> remote_running
  -> downloading_artifacts
  -> importing_model
  -> succeeded
```

Recoverable failures enter `retry_wait` and return to
`waiting_for_worker`. Terminal states are `succeeded`, `failed` and
`cancelled`.

## 6. Safety invariants

- One active lease per task.
- Active assignments never exceed worker capacity.
- Tokens are encrypted at rest and omitted from serialization/logs.
- Dataset IDs and checksums are immutable.
- Remote submission carries a stable idempotency key.
- Artifact filenames are resolved below a task-scoped storage root.
- Imported model filename is unique and a task can import at most one model.
- Queue state is database-backed; in-memory threads are not authoritative.
- A scheduler restart can resume from persisted stages.

## 7. API surface

### Workers

- `GET /api/training-workers`
- `POST /api/training-workers`
- `PUT /api/training-workers/<id>` (rotate URL/token and reconnect in place)
- `POST /api/training-workers/<id>/probe`
- `POST /api/training-workers/<id>/disable`
- `DELETE /api/training-workers/<id>`

### Batches and tasks

- `GET /api/training-batches`
- `POST /api/training-batches`
- `GET /api/training-batches/<id>`
- `POST /api/training-batches/<id>/cancel`
- `POST /api/training-queue-tasks/<id>/retry`
- `GET /api/training-control-plane/status`
- `POST /api/training-control-plane/dispatch`

The dispatch endpoint is an operational/testing trigger. Production runs a
single dedicated scheduler process using the same service method.

## 8. Provider contract

```python
class TrainingWorkerAdapter:
    def health(self): ...
    def upload_dataset(self, dataset): ...
    def submit_job(self, payload, idempotency_key): ...
    def get_job(self, remote_job_id): ...
    def download_artifact(self, remote_job_id, kind, destination): ...
```

Phase 5 implements `ColabHttpWorkerAdapter`. Unsupported capabilities such
as force-cancel are reported explicitly instead of simulated.

## 9. Delivery order

1. Add schema and safe serializers.
2. Add credential encryption and artifact path guards.
3. Add the worker adapter.
4. Add batch creation and queue APIs.
5. Add lease-aware scheduler and retry/recovery.
6. Add automatic model import.
7. Add worker/batch UI.
8. Add Colab idempotency and artifact contract updates.
9. Add dedicated scheduler runner and deployment/runbook instructions.
10. Run unit, integration, concurrency and compatibility tests.

## 10. Definition of Done

- Two registered fake/local workers accept two tasks concurrently.
- A third task waits and starts after capacity is released.
- A worker outage moves a task to retry without losing the batch.
- Restarting the scheduler preserves queued/running state.
- Retrying submission does not create a duplicate remote job.
- Each successful task imports exactly one inactive ONNX model.
- Worker tokens do not appear in API responses, DB plaintext checks or logs.
- Existing Phase 3/4 manual Colab flow remains compatible.
- The complete Python test suite passes.
- The UI shows workers, batches, tasks, attempts and actionable failures.

## 11. Production deployment notes

- Run the Flask web process and scheduler as separate services.
- Deploy exactly one scheduler instance until PostgreSQL row-locking leader
  election is introduced.
- Use PostgreSQL for production concurrency; SQLite remains supported for the
  local proof flow.
- Do not expose the current Flask application directly to the Internet. The
  repository has no user/RBAC boundary; production must add application auth
  or place all UI/API routes behind an authenticated reverse proxy.
- Set `TOOLIB_WORKER_CREDENTIAL_KEY` from a secret manager.
- Store artifacts through a task-scoped storage adapter; local disk is the
  Phase 5 implementation and can later be replaced with S3/GCS/MinIO.
