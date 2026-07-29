import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


CATALOG_PATH = (
    Path(__file__).resolve().parent
    / 'config'
    / 'training_model_catalog.json'
)
ALLOWED_FAMILIES = {'yolo11', 'yolo12', 'yolo26'}
ALLOWED_SCALES = {'n', 's', 'm', 'l', 'x'}
ALLOWED_TASKS = {'detect'}
ALLOWED_STATUSES = {'experimental', 'validated', 'disabled'}
REQUIRED_MODEL_FIELDS = {
    'id',
    'family',
    'family_label',
    'scale',
    'scale_label',
    'checkpoint',
    'task',
    'status',
    'enabled',
}


def _required_string(payload, field, context):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{context}.{field} must be a non-empty string.')
    return value.strip()


def validate_training_model_catalog(payload):
    if not isinstance(payload, dict):
        raise ValueError('Training model catalog must be a JSON object.')

    schema_version = payload.get('schema_version')
    if not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError('schema_version must be a positive integer.')

    catalog_version = _required_string(
        payload,
        'catalog_version',
        'catalog',
    )
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', catalog_version):
        raise ValueError(
            'catalog_version may contain lowercase letters, numbers, dot, '
            'underscore and hyphen only.'
        )

    default_checkpoint = _required_string(
        payload,
        'default_checkpoint',
        'catalog',
    )
    raw_models = payload.get('models')
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError('models must be a non-empty JSON array.')

    model_ids = set()
    checkpoints = set()
    normalized_models = []
    for index, raw_model in enumerate(raw_models):
        context = f'models[{index}]'
        if not isinstance(raw_model, dict):
            raise ValueError(f'{context} must be a JSON object.')
        missing_fields = REQUIRED_MODEL_FIELDS - set(raw_model)
        if missing_fields:
            raise ValueError(
                f'{context} is missing fields: '
                + ', '.join(sorted(missing_fields))
                + '.'
            )

        model_id = _required_string(raw_model, 'id', context)
        family = _required_string(raw_model, 'family', context).lower()
        family_label = _required_string(raw_model, 'family_label', context)
        scale = _required_string(raw_model, 'scale', context).lower()
        scale_label = _required_string(raw_model, 'scale_label', context)
        checkpoint = _required_string(raw_model, 'checkpoint', context)
        task = _required_string(raw_model, 'task', context).lower()
        status = _required_string(raw_model, 'status', context).lower()
        enabled = raw_model.get('enabled')

        if family not in ALLOWED_FAMILIES:
            raise ValueError(f'{context}.family is not supported.')
        if scale not in ALLOWED_SCALES:
            raise ValueError(f'{context}.scale is not supported.')
        if task not in ALLOWED_TASKS:
            raise ValueError(f'{context}.task is not supported.')
        if status not in ALLOWED_STATUSES:
            raise ValueError(f'{context}.status is not supported.')
        if not isinstance(enabled, bool):
            raise ValueError(f'{context}.enabled must be a boolean.')
        if status == 'disabled' and enabled:
            raise ValueError(f'{context} cannot be enabled with disabled status.')
        if model_id in model_ids:
            raise ValueError(f'Duplicate model id: {model_id}.')
        if checkpoint in checkpoints:
            raise ValueError(f'Duplicate checkpoint: {checkpoint}.')
        if model_id != f'{family}{scale}':
            raise ValueError(f'{context}.id must equal family + scale.')
        if checkpoint != f'{model_id}.pt':
            raise ValueError(
                f'{context}.checkpoint must be the official {model_id}.pt name.'
            )

        model_ids.add(model_id)
        checkpoints.add(checkpoint)
        normalized_models.append({
            'id': model_id,
            'family': family,
            'family_label': family_label,
            'scale': scale,
            'scale_label': scale_label,
            'checkpoint': checkpoint,
            'task': task,
            'status': status,
            'enabled': enabled,
        })

    enabled_checkpoints = {
        model['checkpoint']
        for model in normalized_models
        if model['enabled']
    }
    if not enabled_checkpoints:
        raise ValueError('Training model catalog must enable at least one model.')
    if default_checkpoint not in enabled_checkpoints:
        raise ValueError('default_checkpoint must reference an enabled model.')

    return {
        'schema_version': schema_version,
        'catalog_version': catalog_version,
        'default_checkpoint': default_checkpoint,
        'models': normalized_models,
    }


def load_training_model_catalog(path=CATALOG_PATH):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Could not load training model catalog: {exc}') from exc
    return validate_training_model_catalog(payload)


def training_model_catalog_hash(catalog):
    canonical = json.dumps(
        catalog,
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('ascii')
    return hashlib.sha256(canonical).hexdigest()


TRAINING_MODEL_CATALOG = load_training_model_catalog()
TRAINING_MODEL_CATALOG_VERSION = TRAINING_MODEL_CATALOG['catalog_version']
TRAINING_MODEL_CATALOG_HASH = training_model_catalog_hash(
    TRAINING_MODEL_CATALOG
)
ENABLED_TRAINING_MODEL_ENTRIES = tuple(
    model
    for model in TRAINING_MODEL_CATALOG['models']
    if model['enabled']
)
ENABLED_TRAINING_MODEL_CHECKPOINTS = tuple(
    model['checkpoint']
    for model in ENABLED_TRAINING_MODEL_ENTRIES
)
ENABLED_TRAINING_MODEL_CHECKPOINT_SET = frozenset(
    ENABLED_TRAINING_MODEL_CHECKPOINTS
)


def public_training_model_catalog():
    return {
        'schema_version': TRAINING_MODEL_CATALOG['schema_version'],
        'version': TRAINING_MODEL_CATALOG_VERSION,
        'hash': TRAINING_MODEL_CATALOG_HASH,
        'default_checkpoint': TRAINING_MODEL_CATALOG['default_checkpoint'],
        'models': deepcopy(TRAINING_MODEL_CATALOG['models']),
    }
