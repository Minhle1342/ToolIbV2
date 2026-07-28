import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / 'templates' / 'colab_manager.html'
MODELS_TEMPLATE_PATH = REPO_ROOT / 'templates' / 'models_experiment.html'
NOTEBOOK_PATH = REPO_ROOT / 'notebooks' / 'Colab_FastAPI_PoC.ipynb'


def test_colab_manager_contains_phase3_history_resume_and_import_contracts():
    html = TEMPLATE_PATH.read_text(encoding='utf-8')

    for expected in (
        'id="colabTrainingHistoryList"',
        'function loadColabTrainingHistory()',
        'function resumeColabTrainingJob(job)',
        'function importColabTrainingModel(job, button)',
        '"/api/training-jobs/sync"',
        '"/api/models"',
        'formData.append("training_job_id"',
        '/artifacts/onnx',
    ):
        assert expected in html

    assert html.count('id="colabTrainingHistoryList"') == 1
    assert 'sessionStorage.setItem(COLAB_REMOTE_TOKEN_KEY' in html
    assert not re.search(
        r'localStorage\.setItem\(\s*COLAB_REMOTE_TOKEN_KEY',
        html,
    )


def test_notebook_exposes_authenticated_path_safe_onnx_download():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding='utf-8'))
    source = '\n'.join(
        ''.join(cell.get('source', []))
        for cell in notebook['cells']
    )

    for expected in (
        'from fastapi.responses import FileResponse, JSONResponse',
        '"/api/jobs/{job_id}/artifacts/{artifact_kind}"',
        'dependencies=[Depends(require_api_token)]',
        '(DRIVE_ARTIFACT_ROOT / job_id).resolve()',
        '(LOCAL_ARTIFACT_ROOT / job_id).resolve()',
        'root in artifact_path.parents',
        'artifact_path.suffix.lower() != expected_suffix',
        'return FileResponse(',
    ):
        assert expected in source


def test_imported_model_requires_explicit_smoke_test_activation():
    html = MODELS_TEMPLATE_PATH.read_text(encoding='utf-8')

    assert 'm.activation_ready === false' in html
    assert 'Needs smoke test' in html
