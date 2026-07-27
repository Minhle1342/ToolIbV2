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
        'version="0.5.0"',
        'from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status',
        '@app.post("/api/datasets", dependencies=[Depends(require_api_token)])',
        'dataset_id: str = Form(...)',
        'sha256: str = Form(...)',
        'archive: UploadFile = File(...)',
        'actual_sha256 != expected_sha256',
        'DRIVE_DATASET_ROOT',
        'resolve_under(DRIVE_DATASET_ROOT, canonical_id)',
        'dataset_id: str | None = None',
        'data=dataset_info["runtime_yaml"]',
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
        '"gpu_name": torch.cuda.get_device_name(0)',
    ):
        assert expected in source


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
