import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / 'templates' / 'colab_manager.html'
NOTEBOOK_PATH = REPO_ROOT / 'notebooks' / 'Colab_FastAPI_PoC.ipynb'


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
        'parent_artifact_id: str | None = None',
        'parent_sha256: str | None = None',
        '@app.get(\n    "/api/model-artifacts/{artifact_id}"',
        '@app.post("/api/model-artifacts", dependencies=[Depends(require_api_token)])',
        'validate_yolo_checkpoint(local_path)',
        '"model_artifact_upload": True',
        '"training_modes": ["fresh", "finetune"]',
        '"last_pt": (".pt", "last.pt")',
        'model = YOLO(model_source)',
        '"lr0": request_data.lr0',
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
