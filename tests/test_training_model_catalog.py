from copy import deepcopy

import pytest

from training_model_catalog import (
    ENABLED_TRAINING_MODEL_CHECKPOINTS,
    TRAINING_MODEL_CATALOG,
    TRAINING_MODEL_CATALOG_HASH,
    load_training_model_catalog,
    public_training_model_catalog,
    training_model_catalog_hash,
    validate_training_model_catalog,
)
from scripts.sync_phase6_notebook import (
    WORKER_CATALOG_END,
    WORKER_CATALOG_START,
    WORKER_SOURCE_PATH,
    render_worker_catalog_block,
)


def test_phase_a_catalog_enables_only_existing_small_checkpoints():
    expected_checkpoints = tuple(
        f'yolo{family}{scale}.pt'
        for family in (11, 12, 26)
        for scale in ('n', 's', 'm', 'l', 'x')
    )
    assert ENABLED_TRAINING_MODEL_CHECKPOINTS == expected_checkpoints
    assert {
        model['scale']
        for model in TRAINING_MODEL_CATALOG['models']
        if model['enabled']
    } == {'n', 's', 'm', 'l', 'x'}


def test_catalog_hash_is_deterministic_and_public_payload_isolated():
    assert training_model_catalog_hash(
        deepcopy(TRAINING_MODEL_CATALOG)
    ) == TRAINING_MODEL_CATALOG_HASH

    original_checkpoint = TRAINING_MODEL_CATALOG['models'][0]['checkpoint']
    public_payload = public_training_model_catalog()
    public_payload['models'][0]['checkpoint'] = 'modified.pt'
    assert (
        TRAINING_MODEL_CATALOG['models'][0]['checkpoint']
        == original_checkpoint
    )


def test_catalog_loader_reads_and_validates_json(tmp_path):
    catalog_path = tmp_path / 'catalog.json'
    catalog_path.write_text(
        '{"schema_version": 1, "catalog_version": "test-v1", '
        '"default_checkpoint": "yolo11s.pt", "models": ['
        '{"id": "yolo11s", "family": "yolo11", '
        '"family_label": "YOLO11", "scale": "s", '
        '"scale_label": "Small", "checkpoint": "yolo11s.pt", '
        '"task": "detect", "status": "experimental", '
        '"enabled": true}]}',
        encoding='utf-8',
    )
    assert load_training_model_catalog(catalog_path)['catalog_version'] == 'test-v1'


def test_worker_catalog_block_is_generated_from_validated_catalog():
    worker_source = WORKER_SOURCE_PATH.read_text(encoding='utf-8')
    start = worker_source.index(WORKER_CATALOG_START)
    end = worker_source.index(WORKER_CATALOG_END, start)
    end += len(WORKER_CATALOG_END)
    assert worker_source[start:end] == render_worker_catalog_block()


@pytest.mark.parametrize(
    ('mutate', 'expected_error'),
    (
        (
            lambda payload: payload['models'].append(
                deepcopy(payload['models'][0])
            ),
            'Duplicate model id',
        ),
        (
            lambda payload: payload['models'][1].update({
                'checkpoint': payload['models'][0]['checkpoint'],
            }),
            'Duplicate checkpoint',
        ),
        (
            lambda payload: payload['models'][0].update({'family': 'yolov8'}),
            'family is not supported',
        ),
        (
            lambda payload: payload['models'][0].update({'scale': 'tiny'}),
            'scale is not supported',
        ),
        (
            lambda payload: payload['models'][0].update({'task': 'segment'}),
            'task is not supported',
        ),
        (
            lambda payload: payload['models'][0].update({'status': 'ready'}),
            'status is not supported',
        ),
    ),
)
def test_catalog_validator_rejects_drift_and_invalid_entries(
    mutate,
    expected_error,
):
    payload = deepcopy(TRAINING_MODEL_CATALOG)
    mutate(payload)
    with pytest.raises(ValueError, match=expected_error):
        validate_training_model_catalog(payload)
