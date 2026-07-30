from types import SimpleNamespace

from scripts.training_preflight import (
    check_generated_worker,
    check_notebook_sync,
    readiness,
    worker_capability_errors,
)
from training_model_catalog import (
    ENABLED_TRAINING_MODEL_CHECKPOINTS,
    TRAINING_MODEL_CATALOG_HASH,
    TRAINING_MODEL_CATALOG_VERSION,
)
from training_parameter_catalog import (
    TRAINING_PARAMETER_CATALOG_HASH,
    TRAINING_PARAMETER_CATALOG_VERSION,
    TRAINING_PARAMETER_CONTRACT_VERSION,
    TRAINING_PARAMETER_ULTRALYTICS_VERSION,
)


def _worker_health():
    return {
        'gpu_available': True,
        'gpu_name': 'Test GPU',
        'capabilities': {
            'training': True,
            'training_modes': ['fresh', 'finetune'],
            'training_parameter_sets': True,
            'training_parameter_contract_version': (
                TRAINING_PARAMETER_CONTRACT_VERSION
            ),
            'training_parameter_catalog_version': (
                TRAINING_PARAMETER_CATALOG_VERSION
            ),
            'training_parameter_catalog_hash': TRAINING_PARAMETER_CATALOG_HASH,
            'optimizer_contract_version': 1,
            'allowed_models': list(ENABLED_TRAINING_MODEL_CHECKPOINTS),
            'training_model_catalog_version': TRAINING_MODEL_CATALOG_VERSION,
            'training_model_catalog_hash': TRAINING_MODEL_CATALOG_HASH,
            'ultralytics_version': TRAINING_PARAMETER_ULTRALYTICS_VERSION,
            'model_artifact_upload': True,
            'checkpoint_upload': True,
            'checkpoint_resume': True,
        },
    }


def test_repository_worker_and_notebook_are_synchronized():
    assert check_generated_worker()[0].status == 'PASS'
    assert check_notebook_sync()[0].status == 'PASS'


def test_worker_capability_preflight_matches_scheduler_contract():
    assert worker_capability_errors(_worker_health()) == []

    drifted = _worker_health()
    drifted['capabilities']['training_parameter_catalog_hash'] = 'drifted'
    errors = worker_capability_errors(drifted)
    assert any('training_parameter_catalog_hash' in error for error in errors)
    assert any('scheduler rejects' in error for error in errors)


def test_readiness_can_require_runtime_checks():
    skipped = SimpleNamespace(status='SKIP')
    passed = SimpleNamespace(status='PASS')
    failed = SimpleNamespace(status='FAIL')

    assert readiness([passed, skipped], strict=False) == ('READY', 0)
    assert readiness([passed, skipped], strict=True) == ('NOT READY', 1)
    assert readiness([passed, failed], strict=False) == ('NOT READY', 1)
