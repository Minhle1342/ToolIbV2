import json
from pathlib import Path

from training_model_catalog import (
    ENABLED_TRAINING_MODEL_CHECKPOINTS,
    TRAINING_MODEL_CATALOG_HASH,
    TRAINING_MODEL_CATALOG_VERSION,
)
from training_parameter_catalog import (
    TRAINING_PARAMETER_CATALOG_HASH,
    TRAINING_PARAMETER_CATALOG_VERSION,
    TRAINING_PARAMETER_CONTRACT_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / 'templates' / 'colab_manager.html'
NOTEBOOK_PATH = REPO_ROOT / 'notebooks' / 'Colab_FastAPI_PoC.ipynb'
WORKER_PATH = REPO_ROOT / 'notebooks' / 'colab_worker_phase6.py'


def notebook_source():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding='utf-8'))
    return '\n'.join(
        ''.join(cell.get('source', []))
        for cell in notebook['cells']
    )


def test_colab_manager_requires_uploaded_project_snapshot_before_training():
    html = TEMPLATE_PATH.read_text(encoding='utf-8')

    for expected in (
        'id="colabDatasetProject"',
        'id="colabDatasetPrepareBtn"',
        'function prepareAndUploadColabDataset()',
        '"/api/training-datasets"',
        '`/api/training-datasets/${prepared.id}/upload`',
        'dataset_id: colabPreparedDataset.dataset_id',
        'dataset_id: requestPayload.dataset_id',
        'colabPreparedDataset?.status === "uploaded"',
    ):
        assert expected in html

    assert html.count('id="colabDatasetProject"') == 1
    assert 'api_token: credentials.token' in html
    assert 'localStorage.setItem(COLAB_REMOTE_TOKEN_KEY' not in html


def test_colab_remote_catalog_supports_exact_small_detection_models():
    html = TEMPLATE_PATH.read_text(encoding='utf-8')
    source = notebook_source()
    worker = WORKER_PATH.read_text(encoding='utf-8')
    expected_checkpoints = tuple(
        f'yolo{family}{scale}.pt'
        for family in (11, 12, 26)
        for scale in ('n', 's', 'm', 'l', 'x')
    )

    assert '/api/training-model-catalog' in html
    assert 'YOLO_CHECKPOINTS_MAP' not in html
    assert 'COLAB_REMOTE_ALLOWED_MODELS' not in html
    assert 'trainingModelAllowedCheckpoints' in html
    assert tuple(ENABLED_TRAINING_MODEL_CHECKPOINTS) == expected_checkpoints
    for checkpoint in expected_checkpoints:
        assert checkpoint in source
        assert checkpoint in worker
    assert '{"yolo11s.pt", "yolo12s.pt", "yolo26s.pt"}' not in source
    for generated in (
        f'TRAINING_MODEL_CATALOG_VERSION = "{TRAINING_MODEL_CATALOG_VERSION}"',
        f'TRAINING_MODEL_CATALOG_HASH = "{TRAINING_MODEL_CATALOG_HASH}"',
    ):
        assert generated in worker
        assert generated in source
    assert 'yolov12' not in html
    assert 'ultralytics==8.4.110' in html
    assert '"ultralytics==8.4.110"' in source
    assert 'model: str = "yolo11s.pt"' in source
    assert 'SMOKE_MODEL = "yolo11s.pt"' in source
    assert (
        'SMOKE_IMGSZ = 640  # @param [320, 416, 512, 640, 768, 1024]'
        in source
    )
    assert '"allowed_models": sorted(ALLOWED_MODELS)' in source
    assert '"ultralytics_version": ULTRALYTICS_VERSION' in source
    assert 'ULTRALYTICS_PIN = "8.4.110"' in worker
    assert worker in source


def test_notebook_accepts_authenticated_checksum_bound_dataset_snapshots():
    source = notebook_source()

    for expected in (
        'python-multipart>=0.0.20,<1',
        'version="0.8.0"',
        'from fastapi import (',
        '@app.post("/api/datasets", dependencies=[Depends(require_api_token)])',
        'dataset_id: str = Form(...)',
        'sha256: str = Form(...)',
        'archive: UploadFile = File(...)',
        'actual_sha256 != expected_sha256',
        'DRIVE_DATASET_ROOT',
        'resolve_under(DRIVE_DATASET_ROOT, canonical_id)',
        'dataset_id: str | None = None',
        '"data": dataset_info["runtime_yaml"]',
        '"dataset_id": dataset_info["dataset_id"]',
    ):
        assert expected in source


def test_notebook_exposes_phase5_worker_capabilities_and_idempotent_submit():
    source = notebook_source()

    for expected in (
        'IDEMPOTENCY_INDEX: dict[str, str] = {}',
        'idempotency_key: str | None',
        'request.headers.get("Idempotency-Key")',
        'idempotent_replay',
        '"max_concurrent_jobs": 1',
        '"idempotent_submit": True',
        'torch.cuda.get_device_name(0) if gpu_available else None',
    ):
        assert expected in source


def test_notebook_exposes_phase6_parent_cache_finetune_and_artifacts():
    source = notebook_source()

    for expected in (
        'training_mode: Literal["fresh", "finetune"] = "fresh"',
        'apply_training_parameters: bool = False',
        "optimizer_mode: Literal['auto', 'explicit'] = 'auto'",
        '"optimizer_contract_version": 1',
        'parent_artifact_id: str | None = None',
        'parent_sha256: str | None = None',
        '@app.get(\n    "/api/model-artifacts/{artifact_id}"',
        '@app.post("/api/model-artifacts", dependencies=[Depends(require_api_token)])',
        'validate_yolo_checkpoint(local_path)',
        '"model_artifact_upload": True',
        '"training_modes": ["fresh", "finetune"]',
        '"training_parameter_sets": True',
        '"training_model_catalog_version": TRAINING_MODEL_CATALOG_VERSION',
        '"training_model_catalog_hash": TRAINING_MODEL_CATALOG_HASH',
        '"training_parameter_catalog_hash": (',
        '"last_pt": (".pt", "last.pt")',
        'model = YOLO(model_source)',
        'or request_data.apply_training_parameters',
        'train_kwargs["lr0"] = request_data.lr0',
        'model.add_callback(\n            "on_pretrain_routine_end",',
        '"optimizer_class": type(optimizer).__name__',
        '"requested_config": job_snapshot.get("request")',
        '"effective_config": effective_config',
        'Parent checkpoint classes do not match dataset classes.',
    ):
        assert expected in source


def test_notebook_exposes_phase7_checkpoint_upload_and_resume_contract():
    source = notebook_source()

    for expected in (
        'execution_mode: Literal["initial", "resume"] = "initial"',
        'class CheckpointUploadTarget(BaseModel):',
        'class ResumeCheckpoint(BaseModel):',
        '"checkpoint_upload": True',
        '"checkpoint_resume": True',
        'model.add_callback("on_model_save", on_model_save)',
        'requests.put(',
        'requests.get(',
        'model.train(resume=True)',
        '"checkpoint_uploads",',
        '"resume_checkpoint",',
    ):
        assert expected in source

    public_request_start = source.index(
        'def public_train_request(request_data: TrainRequest) -> dict:'
    )
    public_request_end = source.index(
        '\ndef utc_now() -> str:',
        public_request_start,
    )
    public_request_source = source[
        public_request_start:public_request_end
    ]
    assert '"checkpoint_uploads"' in public_request_source
    assert '"resume_checkpoint"' in public_request_source


def test_notebook_falls_back_to_last_checkpoint_when_best_is_missing():
    source = notebook_source()
    worker = WORKER_PATH.read_text(encoding='utf-8')

    for generated_source in (worker, source):
        for expected in (
            'best_pt_available = best_pt.is_file()',
            'selected_checkpoint = best_pt if best_pt_available else last_pt',
            'selected_checkpoint_kind = "best" if best_pt_available else "last"',
            'if not selected_checkpoint.is_file():',
            'export_model = YOLO(str(selected_checkpoint))',
            'shutil.copy2(selected_checkpoint, pt_target)',
            '"selected_checkpoint_kind": selected_checkpoint_kind',
            '"best_pt_available": best_pt_available',
        ):
            assert expected in generated_source
        assert 'if not best_pt.is_file():' not in generated_source


def test_notebook_exposes_phase8_direct_object_transport_contract():
    source = notebook_source()

    for expected in (
        'class RemoteObjectInput(BaseModel):',
        'class ParentObjectInput(RemoteObjectInput):',
        'class ArtifactUploadTarget(BaseModel):',
        'dataset_object: RemoteObjectInput | None = None',
        'parent_object: ParentObjectInput | None = None',
        'artifact_uploads: list[ArtifactUploadTarget]',
        'def download_verified_object(',
        'def materialize_dataset_object(',
        'def materialize_parent_object(',
        '"/api/model-artifacts/resolve"',
        '"object_input_download": True',
        '"artifact_object_upload": True',
        '"object_transport_protocol_version": 1',
        'Uploading training artifacts to object storage.',
        'artifacts["_objects"] = object_artifacts',
    ):
        assert expected in source

    public_request_start = source.index(
        'def public_train_request(request_data: TrainRequest) -> dict:'
    )
    public_request_end = source.index(
        '\ndef utc_now() -> str:',
        public_request_start,
    )
    public_request_source = source[
        public_request_start:public_request_end
    ]
    assert '"dataset_object"' in public_request_source
    assert '"parent_object"' in public_request_source
    assert '"artifact_uploads"' in public_request_source


def test_notebook_restores_persisted_drive_jobs_after_runtime_restart():
    source = notebook_source()

    for expected in (
        'def restore_persisted_jobs() -> int:',
        'DRIVE_ARTIFACT_ROOT.iterdir()',
        'manifest_path = artifact_dir / "manifest.json"',
        'failure_path = artifact_dir / "failure.json"',
        'RESTORED_JOB_COUNT = restore_persisted_jobs()',
        'IDEMPOTENCY_INDEX[str(idempotency_key)] = job_id',
        '"idempotency_key": job_snapshot.get("idempotency_key")',
    ):
        assert expected in source


def test_notebook_extracts_zip_members_without_extractall():
    source = notebook_source()

    assert 'PurePosixPath(member_name).is_absolute()' in source
    assert '".." in member_parts' in source
    assert 'unix_mode == 0o120000' in source
    assert 'target = resolve_under(destination_root, *member_parts)' in source
    assert 'archive.extractall' not in source


def test_notebook_remains_valid_json():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding='utf-8'))

    assert notebook['nbformat'] == 4
    assert notebook['metadata']['accelerator'] == 'GPU'


def test_notebook_exposes_phase_c_training_parameter_contract():
    source = notebook_source()

    for expected in (
        'class TrainingParameterRequest(BaseModel):',
        'patience: int = Field(default=100, ge=0, le=300)',
        'rect: bool = False',
        "cache: Literal['off', 'ram', 'disk'] = 'off'",
        'amp: bool = True',
        'cos_lr: bool = False',
        'momentum: float = Field(default=0.937, ge=0.0, le=1.0)',
        'weight_decay: float = Field(default=0.0005, ge=0.0, le=1.0)',
        'warmup_epochs: float = Field(default=3.0, ge=0.0, le=100.0)',
        'fraction: float = Field(default=1.0, gt=0.0, le=1.0)',
        'multi_scale: float = Field(default=0.0, ge=0.0, le=1.0)',
        'box: float = Field(default=7.5, ge=0.0, le=100.0)',
        'cls: float = Field(default=0.5, ge=0.0, le=100.0)',
        'dfl: float = Field(default=1.5, ge=0.0, le=100.0)',
        'nbs: int = Field(default=64, ge=1, le=4096)',
        "compile: bool | Literal['default', 'reduce-overhead', 'max-autotune-no-cudagraphs'] = False",
        'channels_last: bool = False',
        (
            'TRAINING_PARAMETER_CONTRACT_VERSION = '
            f'{TRAINING_PARAMETER_CONTRACT_VERSION}'
        ),
        f"TRAINING_PARAMETER_CATALOG_VERSION = '{TRAINING_PARAMETER_CATALOG_VERSION}'",
        f"TRAINING_PARAMETER_CATALOG_HASH = '{TRAINING_PARAMETER_CATALOG_HASH}'",
        'for parameter_name in TRAINING_PARAMETER_SET_FORWARD_FIELDS:',
    ):
        assert expected in source


def test_notebook_reports_effective_phase_c_runtime_arguments():
    source = notebook_source()

    assert '"training_arguments": training_arguments' in source
    assert 'trainer_args = getattr(trainer, "args", None)' in source
    for argument in (
        "'patience'",
        "'rect'",
        "'cache'",
        "'amp'",
        "'cos_lr'",
        "'weight_decay'",
        "'warmup_epochs'",
        "'hsv_h'",
        "'perspective'",
        "'fliplr'",
        "'fraction'",
        "'multi_scale'",
        "'box'",
        "'cls'",
        "'dfl'",
        "'nbs'",
        "'compile'",
        "'channels_last'",
    ):
        assert argument in source
