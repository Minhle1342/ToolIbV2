# 3. Define the authenticated FastAPI app and the single-GPU job worker
import copy
import csv
import hashlib
import json
import secrets
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from ultralytics import YOLO

MODEL_CACHE_ROOT = WORK_ROOT / "models"
MODEL_UPLOAD_ROOT = WORK_ROOT / "model_uploads"
DRIVE_MODEL_ROOT = Path("/content/drive/MyDrive/ToolIb_PoC/models")
MAX_MODEL_ARTIFACT_BYTES = 2 * 1024**3
for directory in (MODEL_CACHE_ROOT, MODEL_UPLOAD_ROOT, DRIVE_MODEL_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ToolIbV2 Colab Training Worker", version="0.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5000",
        "https://localhost:5000",
        "http://127.0.0.1:5000",
        "https://127.0.0.1:5000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
bearer_scheme = HTTPBearer(auto_error=False)
JOB_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
IDEMPOTENCY_INDEX: dict[str, str] = {}
MODEL_CACHE: dict[str, dict] = {}
ACTIVE_JOB_ID: str | None = None
TRAIN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="toolib-yolo")
ACTIVE_STATES = {"queued", "running"}


def canonical_artifact_id(value: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("artifact_id must be a valid UUID.") from exc
    return str(parsed)


def canonical_sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    try:
        if len(normalized) != 64:
            raise ValueError
        int(normalized, 16)
    except ValueError as exc:
        raise ValueError(
            "sha256 must contain 64 hexadecimal characters."
        ) from exc
    return normalized


def normalize_class_names(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        def sort_key(item):
            key = str(item[0])
            return (0, int(key)) if key.isdigit() else (1, key)

        return [
            str(class_name)
            for _key, class_name in sorted(value.items(), key=sort_key)
        ]
    return []


class TrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_mode: Literal["fresh", "finetune"] = "fresh"
    model: str = "yolo11n.pt"
    parent_artifact_id: str | None = None
    parent_sha256: str | None = None
    epochs: int = Field(default=1, ge=1, le=300)
    batch: int = Field(default=4, ge=1, le=64)
    imgsz: Literal[320, 416, 512, 640, 768] = 640
    lr0: float = Field(default=0.0001, gt=0, le=0.1)
    lrf: float = Field(default=0.01, gt=0, le=1)
    freeze: int = Field(default=10, ge=0, le=100)
    mosaic: float = Field(default=0.5, ge=0, le=1)
    scale: float = Field(default=0.8, ge=0, le=2)
    close_mosaic: int = Field(default=10, ge=0, le=100)
    degrees: float = Field(default=15.0, ge=0, le=180)
    translate: float = Field(default=0.2, ge=0, le=1)
    mixup: float = Field(default=0.0, ge=0, le=1)
    copy_paste: float = Field(default=0.0, ge=0, le=1)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    dataset_id: str | None = None
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    @field_validator("model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("model must not be empty.")
        return normalized

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, value: str | None) -> str | None:
        return canonical_dataset_id(value) if value else None

    @model_validator(mode="after")
    def validate_training_contract(self):
        if self.training_mode == "fresh":
            if self.model not in ALLOWED_MODELS:
                raise ValueError(
                    f"model must be one of {sorted(ALLOWED_MODELS)}"
                )
            if self.parent_artifact_id or self.parent_sha256:
                raise ValueError(
                    "Fresh training must not supply a parent artifact."
                )
            return self

        if not self.parent_artifact_id or not self.parent_sha256:
            raise ValueError(
                "Fine-tune requires parent_artifact_id and parent_sha256."
            )
        self.parent_artifact_id = canonical_artifact_id(
            self.parent_artifact_id
        )
        self.parent_sha256 = canonical_sha256(self.parent_sha256)
        return self


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, API_TOKEN)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_public_job(job_id: str) -> dict:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return copy.deepcopy(job)


def update_job(job_id: str, **updates) -> None:
    with JOB_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def restore_persisted_jobs() -> int:
    restored = 0
    if not DRIVE_ARTIFACT_ROOT.is_dir():
        return restored

    for artifact_dir in DRIVE_ARTIFACT_ROOT.iterdir():
        if not artifact_dir.is_dir():
            continue
        try:
            job_id = str(uuid.UUID(artifact_dir.name))
        except ValueError:
            continue

        manifest_path = artifact_dir / "manifest.json"
        failure_path = artifact_dir / "failure.json"
        source_path = manifest_path if manifest_path.is_file() else failure_path
        if not source_path.is_file():
            continue
        try:
            persisted = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(persisted.get("job_id") or "") != job_id:
            continue

        request_payload = dict(persisted.get("request") or {})
        model = persisted.get("model") or request_payload.get("model")
        epochs = int(
            persisted.get("epochs") or request_payload.get("epochs") or 1
        )
        batch = int(
            persisted.get("batch") or request_payload.get("batch") or 1
        )
        imgsz = int(
            persisted.get("imgsz") or request_payload.get("imgsz") or 640
        )
        dataset_id = (
            persisted.get("dataset_id") or request_payload.get("dataset_id")
        )
        idempotency_key = (
            persisted.get("idempotency_key")
            or request_payload.pop("idempotency_key", None)
        )
        status_value = str(persisted.get("status") or "failed")
        artifacts = {}
        artifact_filenames = {
            "pt": "best.pt",
            "last_pt": "last.pt",
            "onnx": "best.onnx",
            "results": "results.csv",
            "args": "args.yaml",
        }
        for artifact_kind, filename in artifact_filenames.items():
            artifact_path = artifact_dir / filename
            if artifact_path.is_file():
                artifacts[artifact_kind] = str(artifact_path)
        if manifest_path.is_file():
            artifacts["manifest"] = str(manifest_path)
        if failure_path.is_file():
            artifacts["failure"] = str(failure_path)

        job = {
            "job_id": job_id,
            "status": status_value,
            "created_at": (
                persisted.get("created_at") or persisted.get("finished_at")
            ),
            "started_at": persisted.get("started_at"),
            "finished_at": persisted.get("finished_at"),
            "current_epoch": epochs if status_value == "succeeded" else 0,
            "total_epochs": epochs,
            "message": (
                "Training and ONNX export completed."
                if status_value == "succeeded"
                else "Training job failed."
            ),
            "error": persisted.get("error"),
            "artifacts": artifacts or None,
            "metrics": persisted.get("metrics") or {},
            "dataset_id": dataset_id,
            "idempotency_key": idempotency_key,
            "request": {
                **request_payload,
                "model": model,
                "epochs": epochs,
                "batch": batch,
                "imgsz": imgsz,
                "dataset_id": dataset_id,
            },
        }
        with JOB_LOCK:
            JOBS[job_id] = job
            if idempotency_key:
                IDEMPOTENCY_INDEX[str(idempotency_key)] = job_id
        restored += 1
    return restored


RESTORED_JOB_COUNT = restore_persisted_jobs()


def normalize_export_path(export_result) -> Path:
    value = export_result
    if isinstance(value, (list, tuple)):
        if not value:
            raise RuntimeError("Ultralytics export returned no artifact path.")
        value = value[0]
    path = Path(str(value)).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Exported ONNX file was not found: {path}")
    return path


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_last_metrics(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return {}
    metrics = {}
    for raw_key, raw_value in rows[-1].items():
        key = str(raw_key or "").strip()
        value = str(raw_value or "").strip()
        if not key or not value:
            continue
        try:
            metrics[key] = float(value)
        except ValueError:
            metrics[key] = value
    return metrics


def validate_yolo_checkpoint(path: Path) -> dict:
    # Owner-supplied PyTorch checkpoints are deserialized only inside this
    # replaceable GPU worker, never inside the ToolIb web/control-plane process.
    model = YOLO(str(path))
    task = str(getattr(model, "task", "") or "")
    class_names = normalize_class_names(getattr(model, "names", None))
    if task != "detect":
        raise RuntimeError(
            f"Only detection checkpoints are supported; received task={task!r}."
        )
    if not class_names:
        raise RuntimeError("Checkpoint does not expose class names.")
    return {"task": task, "class_names": class_names}


def ensure_local_model_cache(
    artifact_id: str,
    expected_sha256: str,
    drive_path: Path,
) -> Path:
    local_dir = resolve_under(MODEL_CACHE_ROOT, artifact_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / "parent.pt"
    if (
        local_path.is_file()
        and sha256_path(local_path) == expected_sha256
    ):
        return local_path
    staged = local_dir / ".parent.pt.copy"
    shutil.copy2(drive_path, staged)
    if sha256_path(staged) != expected_sha256:
        staged.unlink(missing_ok=True)
        raise RuntimeError("Drive parent checkpoint checksum changed.")
    staged.replace(local_path)
    return local_path


def resolve_parent_artifact(
    artifact_id: str | None,
    expected_sha256: str | None,
) -> dict:
    canonical_id = canonical_artifact_id(artifact_id)
    canonical_checksum = canonical_sha256(expected_sha256)
    cached = MODEL_CACHE.get(canonical_id)
    if (
        cached
        and cached.get("sha256") == canonical_checksum
        and Path(cached["runtime_path"]).is_file()
        and sha256_path(Path(cached["runtime_path"])) == canonical_checksum
    ):
        return cached

    drive_dir = resolve_under(DRIVE_MODEL_ROOT, canonical_id)
    drive_path = drive_dir / "parent.pt"
    manifest_path = drive_dir / "manifest.json"
    if not drive_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(
            f"Parent artifact {canonical_id} has not been uploaded."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sha256") != canonical_checksum:
        raise RuntimeError("Parent artifact manifest checksum mismatch.")
    if sha256_path(drive_path) != canonical_checksum:
        raise RuntimeError("Parent artifact file checksum mismatch.")
    runtime_path = ensure_local_model_cache(
        canonical_id,
        canonical_checksum,
        drive_path,
    )
    resolved = {
        "artifact_id": canonical_id,
        "sha256": canonical_checksum,
        "runtime_path": str(runtime_path),
        "drive_path": str(drive_path),
        "task": manifest.get("task"),
        "class_names": manifest.get("class_names") or [],
    }
    MODEL_CACHE[canonical_id] = resolved
    return resolved


@app.get(
    "/api/model-artifacts/{artifact_id}",
    dependencies=[Depends(require_api_token)],
)
def get_model_artifact(artifact_id: str, sha256: str):
    try:
        resolved = resolve_parent_artifact(artifact_id, sha256)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Model cache is invalid: {exc}",
        ) from exc
    return {
        "status": "existing",
        "artifact_id": resolved["artifact_id"],
        "sha256": resolved["sha256"],
        "drive_path": resolved["drive_path"],
        "task": resolved.get("task"),
        "class_names": resolved.get("class_names") or [],
    }


@app.post("/api/model-artifacts", dependencies=[Depends(require_api_token)])
async def upload_model_artifact(
    artifact_id: str = Form(...),
    sha256: str = Form(...),
    artifact: UploadFile = File(...),
):
    try:
        canonical_id = canonical_artifact_id(artifact_id)
        expected_sha256 = canonical_sha256(sha256)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    drive_dir = resolve_under(DRIVE_MODEL_ROOT, canonical_id)
    drive_path = drive_dir / "parent.pt"
    manifest_path = drive_dir / "manifest.json"
    if drive_path.is_file() and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409,
                detail="artifact_id has an unreadable Drive manifest.",
            ) from exc
        if manifest.get("sha256") != expected_sha256:
            raise HTTPException(
                status_code=409,
                detail="artifact_id already exists with a different checksum.",
            )
        runtime_path = ensure_local_model_cache(
            canonical_id,
            expected_sha256,
            drive_path,
        )
        resolved = {
            "status": "existing",
            "artifact_id": canonical_id,
            "sha256": expected_sha256,
            "runtime_path": str(runtime_path),
            "drive_path": str(drive_path),
            "task": manifest.get("task"),
            "class_names": manifest.get("class_names") or [],
        }
        MODEL_CACHE[canonical_id] = resolved
        return resolved

    upload_path = resolve_under(MODEL_UPLOAD_ROOT, f"{canonical_id}.upload")
    upload_path.unlink(missing_ok=True)
    digest = hashlib.sha256()
    uploaded_bytes = 0
    local_dir = resolve_under(MODEL_CACHE_ROOT, canonical_id)
    local_path = local_dir / "parent.pt"
    try:
        with upload_path.open("wb") as output:
            while True:
                chunk = await artifact.read(1024 * 1024)
                if not chunk:
                    break
                uploaded_bytes += len(chunk)
                if uploaded_bytes > MAX_MODEL_ARTIFACT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Model artifact exceeds the size limit.",
                    )
                digest.update(chunk)
                output.write(chunk)
        if uploaded_bytes == 0:
            raise HTTPException(
                status_code=422,
                detail="Model artifact is empty.",
            )
        if digest.hexdigest() != expected_sha256:
            raise HTTPException(
                status_code=422,
                detail="Model artifact checksum does not match sha256.",
            )

        local_dir.mkdir(parents=True, exist_ok=True)
        upload_path.replace(local_path)
        metadata = validate_yolo_checkpoint(local_path)

        drive_dir.mkdir(parents=True, exist_ok=True)
        staged_drive_path = drive_dir / ".parent.pt.upload"
        shutil.copy2(local_path, staged_drive_path)
        staged_drive_path.replace(drive_path)
        manifest = {
            "artifact_id": canonical_id,
            "sha256": expected_sha256,
            "size_bytes": uploaded_bytes,
            "task": metadata["task"],
            "class_names": metadata["class_names"],
            "uploaded_at": utc_now(),
        }
        write_json(manifest_path, manifest)
        resolved = {
            "status": "uploaded",
            "artifact_id": canonical_id,
            "sha256": expected_sha256,
            "runtime_path": str(local_path),
            "drive_path": str(drive_path),
            "task": metadata["task"],
            "class_names": metadata["class_names"],
        }
        MODEL_CACHE[canonical_id] = resolved
        return resolved
    except HTTPException:
        raise
    except Exception as exc:
        local_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Model artifact rejected: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        await artifact.close()
        upload_path.unlink(missing_ok=True)


@app.post("/api/datasets", dependencies=[Depends(require_api_token)])
async def upload_dataset_snapshot(
    dataset_id: str = Form(...),
    sha256: str = Form(...),
    archive: UploadFile = File(...),
):
    try:
        canonical_id = canonical_dataset_id(dataset_id)
        expected_sha256 = canonical_sha256(sha256)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    drive_dataset_dir = resolve_under(DRIVE_DATASET_ROOT, canonical_id)
    drive_archive = drive_dataset_dir / "dataset.zip"
    drive_manifest = drive_dataset_dir / "manifest.json"
    existing_manifest = None
    if drive_manifest.is_file():
        try:
            existing_manifest = json.loads(
                drive_manifest.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="dataset_id has an unreadable Drive manifest.",
            ) from exc
        if not isinstance(existing_manifest, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="dataset_id has an invalid Drive manifest.",
            )
        existing_sha256 = existing_manifest.get("sha256")
        if existing_sha256 and existing_sha256 != expected_sha256:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="dataset_id already exists with a different checksum.",
            )
    if (
        drive_archive.is_file()
        and existing_manifest is not None
        and sha256_path(drive_archive) == expected_sha256
    ):
        return {
            "status": "existing",
            "dataset_id": canonical_id,
            "sha256": expected_sha256,
            "drive_path": str(drive_archive),
            "stats": existing_manifest.get("stats", {}),
        }

    upload_path = resolve_under(DATASET_UPLOAD_ROOT, f"{canonical_id}.upload")
    upload_path.unlink(missing_ok=True)
    digest = hashlib.sha256()
    uploaded_bytes = 0
    try:
        with upload_path.open("wb") as output:
            while True:
                chunk = await archive.read(1024 * 1024)
                if not chunk:
                    break
                uploaded_bytes += len(chunk)
                if uploaded_bytes > MAX_DATASET_ARCHIVE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Dataset archive exceeds the size limit.",
                    )
                digest.update(chunk)
                output.write(chunk)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise HTTPException(
                status_code=422,
                detail="Dataset archive checksum does not match sha256.",
            )

        prepared = prepare_runtime_dataset(canonical_id, upload_path)
        if (
            drive_archive.is_file()
            and sha256_path(drive_archive) != expected_sha256
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="dataset_id already exists with a different archive.",
            )
        drive_dataset_dir.mkdir(parents=True, exist_ok=True)
        staged_archive = drive_dataset_dir / ".dataset.zip.upload"
        shutil.copy2(upload_path, staged_archive)
        staged_archive.replace(drive_archive)
        stats = {
            "train": prepared["train_count"],
            "val": prepared["val_count"],
            "test": prepared["test_count"],
            "classes": prepared["class_names"],
        }
        manifest = {
            "dataset_id": canonical_id,
            "sha256": expected_sha256,
            "archive_size": uploaded_bytes,
            "drive_path": str(drive_archive),
            "stats": stats,
            "uploaded_at": utc_now(),
        }
        write_json(drive_manifest, manifest)
        DATASET_CACHE[canonical_id] = prepared
        return {
            "status": "uploaded",
            "dataset_id": canonical_id,
            "sha256": expected_sha256,
            "drive_path": str(drive_archive),
            "stats": stats,
        }
    except HTTPException:
        raise
    except (
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        yaml.YAMLError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset snapshot rejected: {exc}",
        ) from exc
    finally:
        await archive.close()
        upload_path.unlink(missing_ok=True)


def run_training_job(
    job_id: str,
    request_data: TrainRequest,
    dataset_info: dict,
) -> None:
    global ACTIVE_JOB_ID

    artifact_dir = DRIVE_ARTIFACT_ROOT / job_id
    try:
        artifact_dir.mkdir(parents=True, exist_ok=False)
        update_job(
            job_id,
            status="running",
            started_at=utc_now(),
            message=(
                f"Loading dataset {dataset_info['dataset_id'][:8]} "
                "and starting training."
            ),
        )

        if request_data.training_mode == "finetune":
            parent_info = resolve_parent_artifact(
                request_data.parent_artifact_id,
                request_data.parent_sha256,
            )
            model_source = parent_info["runtime_path"]
        else:
            parent_info = None
            model_source = request_data.model
        model = YOLO(model_source)

        def on_train_epoch_end(trainer) -> None:
            current_epoch = int(getattr(trainer, "epoch", 0)) + 1
            total_epochs = int(
                getattr(trainer, "epochs", request_data.epochs)
            )
            update_job(
                job_id,
                current_epoch=current_epoch,
                total_epochs=total_epochs,
                message=f"Training epoch {current_epoch}/{total_epochs}.",
            )

        model.add_callback("on_train_epoch_end", on_train_epoch_end)
        train_kwargs = {
            "data": dataset_info["runtime_yaml"],
            "epochs": request_data.epochs,
            "batch": request_data.batch,
            "imgsz": request_data.imgsz,
            "device": 0,
            "workers": 2,
            "project": str(LOCAL_RUN_ROOT),
            "name": job_id,
            "exist_ok": False,
            "seed": request_data.seed,
        }
        if request_data.training_mode == "finetune":
            train_kwargs.update({
                "lr0": request_data.lr0,
                "lrf": request_data.lrf,
                "freeze": request_data.freeze,
                "mosaic": request_data.mosaic,
                "scale": request_data.scale,
                "close_mosaic": min(
                    request_data.close_mosaic,
                    max(request_data.epochs - 1, 0),
                ),
                "degrees": request_data.degrees,
                "translate": request_data.translate,
                "mixup": request_data.mixup,
                "copy_paste": request_data.copy_paste,
            })
        model.train(**train_kwargs)

        trainer = getattr(model, "trainer", None)
        save_dir_value = getattr(trainer, "save_dir", None)
        if save_dir_value is None:
            raise RuntimeError(
                "Ultralytics did not expose the training save directory."
            )
        save_dir = Path(str(save_dir_value)).resolve()
        best_pt = save_dir / "weights" / "best.pt"
        last_pt = save_dir / "weights" / "last.pt"
        if not best_pt.is_file():
            raise FileNotFoundError(
                f"Training completed but best.pt was not found: {best_pt}"
            )

        update_job(job_id, message="Exporting best.pt to ONNX.")
        export_model = YOLO(str(best_pt))
        export_result = export_model.export(
            format="onnx",
            dynamic=True,
            imgsz=request_data.imgsz,
        )
        exported_onnx = normalize_export_path(export_result)

        pt_target = artifact_dir / "best.pt"
        last_pt_target = artifact_dir / "last.pt"
        onnx_target = artifact_dir / "best.onnx"
        shutil.copy2(best_pt, pt_target)
        if last_pt.is_file():
            shutil.copy2(last_pt, last_pt_target)
        shutil.copy2(exported_onnx, onnx_target)

        copied_artifacts = {}
        for filename, artifact_kind in (
            ("results.csv", "results"),
            ("args.yaml", "args"),
        ):
            source = save_dir / filename
            if source.is_file():
                destination = artifact_dir / filename
                shutil.copy2(source, destination)
                copied_artifacts[artifact_kind] = str(destination)
        metrics = read_last_metrics(save_dir / "results.csv")

        manifest_path = artifact_dir / "manifest.json"
        job_snapshot = get_public_job(job_id)
        artifacts = {
            "pt": str(pt_target),
            "onnx": str(onnx_target),
            **copied_artifacts,
        }
        if last_pt_target.is_file():
            artifacts["last_pt"] = str(last_pt_target)
        manifest = {
            "job_id": job_id,
            "status": "succeeded",
            "created_at": job_snapshot.get("created_at"),
            "started_at": job_snapshot.get("started_at"),
            "training_mode": request_data.training_mode,
            "model": request_data.model,
            "epochs": request_data.epochs,
            "batch": request_data.batch,
            "imgsz": request_data.imgsz,
            "dataset_id": dataset_info["dataset_id"],
            "parent_artifact_id": request_data.parent_artifact_id,
            "parent_sha256": request_data.parent_sha256,
            "idempotency_key": job_snapshot.get("idempotency_key"),
            "request": job_snapshot.get("request"),
            "dataset_yaml": dataset_info["runtime_yaml"],
            "training_save_dir": str(save_dir),
            "metrics": metrics,
            "artifacts": artifacts,
            "finished_at": utc_now(),
        }
        write_json(manifest_path, manifest)
        artifacts["manifest"] = str(manifest_path)

        update_job(
            job_id,
            status="succeeded",
            finished_at=manifest["finished_at"],
            current_epoch=request_data.epochs,
            total_epochs=request_data.epochs,
            message="Training and ONNX export completed.",
            error=None,
            metrics=metrics,
            artifacts=artifacts,
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        failure_path = artifact_dir / "failure.json"
        failure = {
            "job_id": job_id,
            "status": "failed",
            "request": request_data.model_dump(),
            "error": error_message,
            "finished_at": utc_now(),
        }
        try:
            write_json(failure_path, failure)
        except Exception as persist_exc:
            error_message += f"; could not persist failure: {persist_exc}"
        update_job(
            job_id,
            status="failed",
            finished_at=failure["finished_at"],
            message="Training job failed.",
            error=error_message,
            artifacts=(
                {"failure": str(failure_path)}
                if failure_path.exists()
                else None
            ),
        )
    finally:
        with JOB_LOCK:
            if ACTIVE_JOB_ID == job_id:
                ACTIVE_JOB_ID = None


@app.get("/health")
def health() -> dict:
    with JOB_LOCK:
        active_job_id = ACTIVE_JOB_ID
    gpu_available = bool(torch.cuda.is_available())
    return {
        "status": "online",
        "gpu_available": gpu_available,
        "gpu_name": (
            torch.cuda.get_device_name(0) if gpu_available else None
        ),
        "active_job_id": active_job_id,
        "idempotent_submit": True,
        "capabilities": {
            "dataset_upload": True,
            "model_artifact_upload": True,
            "training": True,
            "training_modes": ["fresh", "finetune"],
            "artifact_download": [
                "onnx",
                "pt",
                "last_pt",
                "manifest",
                "results",
                "args",
            ],
            "max_concurrent_jobs": 1,
            "idempotent_submit": True,
        },
    }


@app.post("/api/train", dependencies=[Depends(require_api_token)])
def start_train(request_data: TrainRequest, request: Request):
    global ACTIVE_JOB_ID
    header_key = (
        str(request.headers.get("Idempotency-Key") or "").strip() or None
    )
    body_key = request_data.idempotency_key
    if header_key and body_key and header_key != body_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency key mismatch.",
        )
    idempotency_key = header_key or body_key

    try:
        dataset_info = resolve_training_dataset(request_data.dataset_id)
        if request_data.training_mode == "finetune":
            parent_info = resolve_parent_artifact(
                request_data.parent_artifact_id,
                request_data.parent_sha256,
            )
            if normalize_class_names(parent_info.get("class_names")) != (
                normalize_class_names(dataset_info.get("class_names"))
            ):
                raise ValueError(
                    "Parent checkpoint classes do not match dataset classes."
                )
    except (
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        yaml.YAMLError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Training inputs are not ready: {exc}",
        ) from exc

    with JOB_LOCK:
        if idempotency_key and idempotency_key in IDEMPOTENCY_INDEX:
            replay_job_id = IDEMPOTENCY_INDEX[idempotency_key]
            replay_job = copy.deepcopy(JOBS[replay_job_id])
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "job_id": replay_job_id,
                    "status": replay_job["status"],
                    "dataset_id": replay_job["dataset_id"],
                    "idempotent_replay": True,
                },
            )
        if ACTIVE_JOB_ID is not None:
            active_job = JOBS.get(ACTIVE_JOB_ID, {})
            if active_job.get("status") in ACTIVE_STATES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "A training job is already active.",
                        "active_job_id": ACTIVE_JOB_ID,
                    },
                )

        job_id = str(uuid.uuid4())
        ACTIVE_JOB_ID = job_id
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "current_epoch": 0,
            "total_epochs": request_data.epochs,
            "message": "Training job accepted.",
            "error": None,
            "artifacts": None,
            "metrics": {},
            "dataset_id": dataset_info["dataset_id"],
            "idempotency_key": idempotency_key,
            "request": request_data.model_dump(
                exclude={"idempotency_key"}
            ),
        }
        if idempotency_key:
            IDEMPOTENCY_INDEX[idempotency_key] = job_id

    try:
        TRAIN_EXECUTOR.submit(
            run_training_job,
            job_id,
            request_data,
            dataset_info,
        )
    except Exception as exc:
        with JOB_LOCK:
            ACTIVE_JOB_ID = None
            JOBS[job_id].update(
                status="failed",
                finished_at=utc_now(),
                message="Could not submit training job.",
                error=f"{type(exc).__name__}: {exc}",
            )
        raise HTTPException(
            status_code=500,
            detail="Could not submit training job.",
        ) from exc

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job_id": job_id,
            "status": "queued",
            "dataset_id": dataset_info["dataset_id"],
            "idempotent_replay": False,
        },
    )


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_api_token)])
def get_job(job_id: str) -> dict:
    return get_public_job(job_id)


ARTIFACT_SPECS = {
    "onnx": (".onnx", "best.onnx"),
    "pt": (".pt", "best.pt"),
    "last_pt": (".pt", "last.pt"),
    "manifest": (".json", "manifest.json"),
    "results": (".csv", "results.csv"),
    "args": (".yaml", "args.yaml"),
}


@app.get(
    "/api/jobs/{job_id}/artifacts/{artifact_kind}",
    dependencies=[Depends(require_api_token)],
)
def download_job_artifact(job_id: str, artifact_kind: str):
    job = get_public_job(job_id)
    if job.get("status") != "succeeded":
        raise HTTPException(
            status_code=409,
            detail="Training job has not succeeded.",
        )
    artifact_spec = ARTIFACT_SPECS.get(artifact_kind)
    if artifact_spec is None:
        raise HTTPException(
            status_code=404,
            detail="Unsupported artifact kind.",
        )
    artifact_value = (job.get("artifacts") or {}).get(artifact_kind)
    if not artifact_value:
        raise HTTPException(
            status_code=404,
            detail=f"{artifact_kind} artifact is not available.",
        )

    artifact_root = (DRIVE_ARTIFACT_ROOT / job_id).resolve()
    artifact_path = Path(str(artifact_value)).resolve()
    try:
        artifact_path.relative_to(artifact_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid artifact path.",
        ) from exc
    expected_suffix, download_name = artifact_spec
    if (
        artifact_path.suffix.lower() != expected_suffix
        or not artifact_path.is_file()
    ):
        raise HTTPException(
            status_code=404,
            detail="Artifact file was not found.",
        )
    return FileResponse(
        path=artifact_path,
        media_type="application/octet-stream",
        filename=f"{job_id[:8]}-{download_name}",
    )


print("FastAPI application created.")
print("Allowed fresh models:", sorted(ALLOWED_MODELS))
print("Fine-tune parent cache:", DRIVE_MODEL_ROOT)
print("Restored persisted jobs from Drive:", RESTORED_JOB_COUNT)
