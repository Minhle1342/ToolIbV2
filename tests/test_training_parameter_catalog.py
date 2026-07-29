import json
from pathlib import Path

import pytest

from scripts.sync_phase6_notebook import render_worker_parameter_block
from training_parameter_catalog import (
    TRAINING_PARAMETER_CATALOG_HASH,
    TRAINING_PARAMETER_CATALOG_VERSION,
    TRAINING_PARAMETER_CONTRACT_VERSION,
    TRAINING_PARAMETER_DEFAULTS,
    TRAINING_PARAMETER_FIELDS,
    TrainingParameterCatalogError,
    load_training_parameter_catalog,
    normalize_training_parameters,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPOSITORY_ROOT / 'config' / 'training_parameter_catalog.json'
WORKER_PATH = REPOSITORY_ROOT / 'notebooks' / 'colab_worker_phase6.py'


def test_phase_c2_catalog_exposes_exact_training_contract():
    assert TRAINING_PARAMETER_CATALOG_VERSION == 'phase-c2-training-v1'
    assert TRAINING_PARAMETER_CONTRACT_VERSION == 3
    assert len(TRAINING_PARAMETER_FIELDS) == 39
    assert {
        'multi_scale',
        'fraction',
        'box',
        'cls',
        'dfl',
        'nbs',
        'compile',
        'channels_last',
    }.issubset(TRAINING_PARAMETER_FIELDS)
    assert TRAINING_PARAMETER_DEFAULTS['multi_scale'] == 0.0
    assert TRAINING_PARAMETER_DEFAULTS['fraction'] == 1.0
    assert TRAINING_PARAMETER_DEFAULTS['box'] == 7.5
    assert TRAINING_PARAMETER_DEFAULTS['cls'] == 0.5
    assert TRAINING_PARAMETER_DEFAULTS['dfl'] == 1.5
    assert TRAINING_PARAMETER_DEFAULTS['nbs'] == 64
    assert TRAINING_PARAMETER_DEFAULTS['compile'] is False
    assert TRAINING_PARAMETER_DEFAULTS['channels_last'] is False


def test_phase_c2_normalization_validates_new_fields_and_legacy_aliases():
    normalized = normalize_training_parameters({
        'multi_scale': 0.5,
        'fraction': 0.75,
        'box': 8,
        'cls': 0.6,
        'dfl': 1.7,
        'nbs': 32,
        'compile': 'reduce-overhead',
        'channels_last': 'true',
        'cache': True,
    })
    assert normalized['multi_scale'] == 0.5
    assert normalized['fraction'] == 0.75
    assert normalized['box'] == 8.0
    assert normalized['compile'] == 'reduce-overhead'
    assert normalized['channels_last'] is True
    assert normalized['cache'] == 'ram'

    for invalid in (
        {'fraction': 0},
        {'multi_scale': 1.1},
        {'nbs': 0},
        {'compile': 'unknown-backend'},
        {'channels_last': 1},
    ):
        with pytest.raises(TrainingParameterCatalogError):
            normalize_training_parameters(invalid)


def test_worker_parameter_contract_is_generated_from_catalog():
    generated = render_worker_parameter_block()
    worker = WORKER_PATH.read_text(encoding='utf-8')

    assert generated in worker
    assert TRAINING_PARAMETER_CATALOG_HASH in generated
    for field in TRAINING_PARAMETER_FIELDS:
        assert f'    {field}:' in generated


def test_catalog_loader_rejects_schema_drift(tmp_path):
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    catalog['fields'].append(dict(catalog['fields'][0]))
    invalid_path = tmp_path / 'duplicate.json'
    invalid_path.write_text(json.dumps(catalog), encoding='utf-8')

    with pytest.raises(TrainingParameterCatalogError, match='duplicate field'):
        load_training_parameter_catalog(invalid_path)
