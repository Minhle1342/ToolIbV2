# Phase 8 - Direct object-storage transport

Phase 8 moves large training payloads off the temporary Cloudflare Tunnel.
ToolIb uploads each immutable dataset snapshot and parent checkpoint to
S3-compatible object storage once. Every compatible Colab worker downloads
those inputs directly to its local disk through a short-lived presigned URL.
After training, the worker uploads result artifacts directly to the same
object store, and ToolIb copies them into its central local artifact store.

The Cloudflare Quick Tunnel remains the control channel for job submission and
status polling. Google Drive and tunnel-based file transfer remain available
as compatibility fallback when object storage or the new worker capability is
not available.

## Runtime flow

```text
Project dataset
  -> ToolIb creates one immutable ZIP snapshot
  -> ToolIb uploads datasets/<sha256>/dataset.zip to R2 once
  -> job request contains a presigned GET URL
  -> each Colab downloads and verifies size + SHA-256
  -> Colab extracts and trains from /content local disk

Parent .pt
  -> ToolIb uploads parents/<sha256>/parent.pt once
  -> each fine-tune worker downloads and validates it locally

Training results
  -> Colab uploads best.pt/best.onnx/last.pt/manifest/results/args by
     task-scoped presigned PUT URLs
  -> ToolIb verifies object key, size, and SHA-256
  -> ToolIb downloads the artifacts into its central artifact store
  -> the candidate model is imported as inactive
```

R2 credentials stay only on the ToolIb machine. Colab receives presigned URLs
for individual objects and never receives the R2 Access Key ID or Secret.
Presigned URLs are excluded from the public job payload returned by the worker.

## Configure and start

Use the same local-only `.env.object-storage.local` described in
`docs/phase7_resumable_training_runbook.md`:

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

Then start ToolIb:

```powershell
.\run.ps1
```

The launcher applies the additive Phase 8 migration automatically. An
independent schema check is also available:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_phase8_object_transport.py --check
```

Expected result:

```text
Phase 8 schema ready (20260728_phase8_object_transport).
```

## Update each Colab worker

Upload and run the current notebook on every Colab account:

```text
notebooks/Colab_FastAPI_PoC.ipynb
```

After registering or probing it from `/colab-manager`, the worker must report:

```json
{
  "object_input_download": true,
  "artifact_object_upload": true,
  "object_transport_protocol_version": 1
}
```

An older worker remains usable but falls back to the previous tunnel/Drive
transport.

## Two-candidate smoke test

1. Keep two current Colab workers online.
2. In `/colab-manager`, choose one parent `.pt`, one project dataset, and two
   fine-tune parameter sets.
3. Queue the fine-tune sweep.
4. Confirm both tasks enter `remote_running`.
5. Confirm R2 contains one dataset object and one parent object, rather than a
   duplicate copy per candidate.
6. When training finishes, confirm task messages move through
   `downloading_artifacts` and `importing_model`.
7. Open `/models-experiment` and confirm two inactive candidate models exist.

The first run uploads the shared dataset/parent. A later sweep using the same
content reuses those object keys after a size check. Each worker still
downloads its own local copy because Colab runtimes do not share a filesystem.

## Acceptance criteria

Phase 8 is accepted after a real R2 + Colab run demonstrates all of the
following:

1. Large dataset/model bytes do not pass through the Quick Tunnel.
2. One immutable dataset snapshot is reused by all candidates.
3. Each worker verifies the downloaded byte count and SHA-256 before use.
4. Training runs against the extracted local Colab path.
5. Result artifacts are uploaded directly from Colab to R2.
6. ToolIb verifies the task-scoped object key, size, and checksum before import.
7. The central local artifact files and database object metadata are present.
8. With object transport disabled, the existing tunnel/Drive fallback still
   completes a small job.

Local automated tests validate the contracts and fallback, but they do not
replace this real cloud acceptance run.
