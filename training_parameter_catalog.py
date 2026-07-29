import copy
import hashlib
import json
from pathlib import Path


CATALOG_PATH = (
    Path(__file__).resolve().parent
    / 'config'
    / 'training_parameter_catalog.json'
)
FIELD_TYPES = {
    'integer',
    'number',
    'nullable_number',
    'boolean',
    'enum',
    'boolean_or_enum',
}
FORWARD_MODES = {'always', 'parameter_set', 'explicit_optimizer', 'never'}


class TrainingParameterCatalogError(ValueError):
    pass


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    )


def _option_values(field):
    return tuple(option['value'] for option in field.get('options', ()))


def _normalize_boolean(name, value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'off'}:
            return False
    raise TrainingParameterCatalogError(f'{name} must be a boolean.')


def _normalize_number(field, value, integer=False, nullable=False):
    name = field['name']
    if value is None and nullable:
        return None
    if isinstance(value, bool):
        kind = 'integer' if integer else 'number'
        raise TrainingParameterCatalogError(f'{name} must be a {kind}.')
    try:
        normalized = int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        kind = 'integer' if integer else 'number'
        raise TrainingParameterCatalogError(f'{name} must be a {kind}.') from exc
    if integer and isinstance(value, float) and not value.is_integer():
        raise TrainingParameterCatalogError(f'{name} must be an integer.')
    minimum = field.get('minimum')
    maximum = field.get('maximum')
    exclusive_minimum = field.get('exclusive_minimum')
    if minimum is not None and normalized < minimum:
        raise TrainingParameterCatalogError(
            f'{name} must be at least {minimum}.'
        )
    if maximum is not None and normalized > maximum:
        raise TrainingParameterCatalogError(
            f'{name} must be at most {maximum}.'
        )
    if exclusive_minimum is not None and normalized <= exclusive_minimum:
        raise TrainingParameterCatalogError(
            f'{name} must be greater than {exclusive_minimum}.'
        )
    return normalized


def normalize_training_parameter_value(field, value):
    for alias in field.get('aliases', ()):
        if value == alias.get('from') and type(value) is type(alias.get('from')):
            value = alias.get('to')
            break
    field_type = field['type']
    name = field['name']
    if field_type == 'integer':
        return _normalize_number(field, value, integer=True)
    if field_type == 'number':
        return _normalize_number(field, value)
    if field_type == 'nullable_number':
        return _normalize_number(field, value, nullable=True)
    if field_type == 'boolean':
        return _normalize_boolean(name, value)
    if field_type == 'boolean_or_enum':
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.lower() in {'false', 'off'}:
                return False
            for option in _option_values(field):
                if normalized.lower() == str(option).lower():
                    return option
        raise TrainingParameterCatalogError(
            f'{name} must be false or one of: '
            + ', '.join(str(value) for value in _option_values(field))
            + '.'
        )
    if field_type == 'enum':
        options = _option_values(field)
        if value in options:
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            for option in options:
                if normalized == str(option).lower():
                    return option
        raise TrainingParameterCatalogError(
            f'{name} must be one of: '
            + ', '.join(str(option) for option in options)
            + '.'
        )
    raise TrainingParameterCatalogError(
        f'Unsupported catalog type for {name}: {field_type}.'
    )


def _validate_catalog(raw_catalog):
    if not isinstance(raw_catalog, dict):
        raise TrainingParameterCatalogError('Catalog root must be an object.')
    version = str(raw_catalog.get('catalog_version') or '').strip()
    if not version:
        raise TrainingParameterCatalogError('catalog_version is required.')
    contract_version = raw_catalog.get('contract_version')
    if not isinstance(contract_version, int) or contract_version < 1:
        raise TrainingParameterCatalogError(
            'contract_version must be a positive integer.'
        )
    ultralytics_version = str(
        raw_catalog.get('ultralytics_version') or ''
    ).strip()
    if not ultralytics_version:
        raise TrainingParameterCatalogError('ultralytics_version is required.')

    groups = raw_catalog.get('groups')
    fields = raw_catalog.get('fields')
    if not isinstance(groups, list) or not groups:
        raise TrainingParameterCatalogError('groups must be a non-empty list.')
    if not isinstance(fields, list) or not fields:
        raise TrainingParameterCatalogError('fields must be a non-empty list.')
    group_ids = []
    for group in groups:
        if not isinstance(group, dict):
            raise TrainingParameterCatalogError('Each group must be an object.')
        group_id = str(group.get('id') or '').strip()
        if not group_id or group_id in group_ids:
            raise TrainingParameterCatalogError(
                f'Invalid or duplicate group id: {group_id!r}.'
            )
        group_ids.append(group_id)

    field_names = []
    for field in fields:
        if not isinstance(field, dict):
            raise TrainingParameterCatalogError('Each field must be an object.')
        name = str(field.get('name') or '').strip()
        if not name or name in field_names:
            raise TrainingParameterCatalogError(
                f'Invalid or duplicate field name: {name!r}.'
            )
        field_names.append(name)
        if field.get('type') not in FIELD_TYPES:
            raise TrainingParameterCatalogError(
                f'{name} has unsupported type {field.get("type")!r}.'
            )
        if field.get('forward') not in FORWARD_MODES:
            raise TrainingParameterCatalogError(
                f'{name} has invalid forward mode.'
            )
        ui = field.get('ui')
        if not isinstance(ui, dict) or ui.get('group') not in group_ids:
            raise TrainingParameterCatalogError(
                f'{name} must reference a valid UI group.'
            )
        options = field.get('options')
        if field['type'] in {'enum', 'boolean_or_enum'}:
            if not isinstance(options, list) or not options:
                raise TrainingParameterCatalogError(
                    f'{name} must define non-empty options.'
                )
            option_values = []
            for option in options:
                if not isinstance(option, dict) or 'value' not in option:
                    raise TrainingParameterCatalogError(
                        f'{name} contains an invalid option.'
                    )
                if option['value'] in option_values:
                    raise TrainingParameterCatalogError(
                        f'{name} contains duplicate option values.'
                    )
                option_values.append(option['value'])
        normalize_training_parameter_value(field, field.get('default'))
        normalize_training_parameter_value(
            field,
            field.get('worker_default', field.get('default')),
        )
    return copy.deepcopy(raw_catalog)


def load_training_parameter_catalog(path=None):
    catalog_path = Path(path or CATALOG_PATH)
    try:
        raw_catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingParameterCatalogError(
            f'Unable to load training parameter catalog: {exc}'
        ) from exc
    return _validate_catalog(raw_catalog)


def normalize_training_parameters(raw_parameters, include_defaults=True):
    if not isinstance(raw_parameters, dict):
        raise TrainingParameterCatalogError('parameters must be a JSON object.')
    unknown = sorted(set(raw_parameters) - set(TRAINING_PARAMETER_FIELDS))
    if unknown:
        raise TrainingParameterCatalogError(
            'Unsupported training parameter(s): ' + ', '.join(unknown)
        )
    normalized = {}
    for field in TRAINING_PARAMETER_FIELD_SPECS:
        name = field['name']
        if name not in raw_parameters and not include_defaults:
            continue
        value = raw_parameters.get(name, field['default'])
        normalized[name] = normalize_training_parameter_value(field, value)
    return normalized


TRAINING_PARAMETER_CATALOG = load_training_parameter_catalog()
TRAINING_PARAMETER_CATALOG_VERSION = TRAINING_PARAMETER_CATALOG[
    'catalog_version'
]
TRAINING_PARAMETER_CONTRACT_VERSION = TRAINING_PARAMETER_CATALOG[
    'contract_version'
]
TRAINING_PARAMETER_ULTRALYTICS_VERSION = TRAINING_PARAMETER_CATALOG[
    'ultralytics_version'
]
TRAINING_PARAMETER_CATALOG_HASH = hashlib.sha256(
    _canonical_json(TRAINING_PARAMETER_CATALOG).encode('ascii')
).hexdigest()
TRAINING_PARAMETER_GROUPS = tuple(TRAINING_PARAMETER_CATALOG['groups'])
TRAINING_PARAMETER_FIELD_SPECS = tuple(TRAINING_PARAMETER_CATALOG['fields'])
TRAINING_PARAMETER_FIELD_MAP = {
    field['name']: field
    for field in TRAINING_PARAMETER_FIELD_SPECS
}
TRAINING_PARAMETER_FIELDS = tuple(TRAINING_PARAMETER_FIELD_MAP)
TRAINING_PARAMETER_DEFAULTS = {
    name: copy.deepcopy(field['default'])
    for name, field in TRAINING_PARAMETER_FIELD_MAP.items()
}
TRAINING_PARAMETER_WORKER_DEFAULTS = {
    name: copy.deepcopy(field.get('worker_default', field['default']))
    for name, field in TRAINING_PARAMETER_FIELD_MAP.items()
}
TRAINING_PARAMETER_ALWAYS_FORWARD_FIELDS = tuple(
    field['name']
    for field in TRAINING_PARAMETER_FIELD_SPECS
    if field['forward'] == 'always'
)
TRAINING_PARAMETER_SET_FORWARD_FIELDS = tuple(
    field['name']
    for field in TRAINING_PARAMETER_FIELD_SPECS
    if field['forward'] == 'parameter_set'
)
TRAINING_PARAMETER_EFFECTIVE_FIELDS = tuple(
    field['name']
    for field in TRAINING_PARAMETER_FIELD_SPECS
    if field.get('effective')
)


def parameter_option_values(name):
    return _option_values(TRAINING_PARAMETER_FIELD_MAP[name])


def training_parameter_catalog_payload():
    return {
        'version': TRAINING_PARAMETER_CATALOG_VERSION,
        'hash': TRAINING_PARAMETER_CATALOG_HASH,
        'contract_version': TRAINING_PARAMETER_CONTRACT_VERSION,
        'ultralytics_version': TRAINING_PARAMETER_ULTRALYTICS_VERSION,
        'groups': copy.deepcopy(list(TRAINING_PARAMETER_GROUPS)),
        'fields': copy.deepcopy(list(TRAINING_PARAMETER_FIELD_SPECS)),
    }
