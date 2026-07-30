import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from database_support import normalize_database_uri
from scripts.migrate_phase9_optimizer_contract import (
    phase9_migration_status,
)
from scripts.sync_phase6_notebook import (
    NOTEBOOK_PATH,
    TARGET_CELL_INDEX,
    WORKER_CATALOG_END,
    WORKER_CATALOG_START,
    WORKER_PARAMETER_END,
    WORKER_PARAMETER_START,
    WORKER_SOURCE_PATH,
    _replace_generated_block,
    render_worker_catalog_block,
    render_worker_parameter_block,
)
from training_control_plane import (
    ColabHttpWorkerAdapter,
    _worker_supports_task,
)
from training_model_catalog import (
    ENABLED_TRAINING_MODEL_CHECKPOINTS,
    TRAINING_MODEL_CATALOG_HASH,
    TRAINING_MODEL_CATALOG_VERSION,
    load_training_model_catalog,
)
from training_parameter_catalog import (
    TRAINING_PARAMETER_CATALOG_HASH,
    TRAINING_PARAMETER_CATALOG_VERSION,
    TRAINING_PARAMETER_CONTRACT_VERSION,
    TRAINING_PARAMETER_FIELDS,
    TRAINING_PARAMETER_ULTRALYTICS_VERSION,
    load_training_parameter_catalog,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def _pass(name, detail):
    return CheckResult(name=name, status='PASS', detail=detail)


def _fail(name, detail):
    return CheckResult(name=name, status='FAIL', detail=detail)


def _skip(name, detail):
    return CheckResult(name=name, status='SKIP', detail=detail)


def check_catalogs():
    try:
        model_catalog = load_training_model_catalog()
        parameter_catalog = load_training_parameter_catalog()
    except (OSError, ValueError) as exc:
        return [_fail('catalogs', str(exc))]
    return [_pass(
        'catalogs',
        (
            f'model={model_catalog["catalog_version"]} '
            f'({len(ENABLED_TRAINING_MODEL_CHECKPOINTS)} enabled), '
            f'parameters={parameter_catalog["catalog_version"]} '
            f'({len(TRAINING_PARAMETER_FIELDS)} fields), '
            f'contract={TRAINING_PARAMETER_CONTRACT_VERSION}'
        ),
    )]


def check_generated_worker():
    try:
        source = WORKER_SOURCE_PATH.read_text(encoding='utf-8')
        expected = _replace_generated_block(
            source,
            WORKER_CATALOG_START,
            WORKER_CATALOG_END,
            render_worker_catalog_block(),
        )
        expected = _replace_generated_block(
            expected,
            WORKER_PARAMETER_START,
            WORKER_PARAMETER_END,
            render_worker_parameter_block(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return [_fail('generated-worker', str(exc))]
    if expected != source:
        return [_fail(
            'generated-worker',
            'worker catalog blocks drifted; run scripts/sync_phase6_notebook.py',
        )]
    return [_pass(
        'generated-worker',
        (
            f'model_hash={TRAINING_MODEL_CATALOG_HASH[:12]}, '
            f'parameter_hash={TRAINING_PARAMETER_CATALOG_HASH[:12]}'
        ),
    )]


def check_notebook_sync():
    try:
        notebook = json.loads(NOTEBOOK_PATH.read_text(encoding='utf-8'))
        cells = notebook.get('cells') or []
        worker_source = WORKER_SOURCE_PATH.read_text(encoding='utf-8')
        notebook_source = ''.join(cells[TARGET_CELL_INDEX].get('source') or [])
    except (IndexError, KeyError, OSError, json.JSONDecodeError) as exc:
        return [_fail('notebook-sync', str(exc))]
    if notebook_source != worker_source:
        return [_fail(
            'notebook-sync',
            'notebook worker cell differs from colab_worker_phase6.py',
        )]
    return [_pass('notebook-sync', 'worker source matches notebook cell')]


def run_code_checks():
    return [
        *check_catalogs(),
        *check_generated_worker(),
        *check_notebook_sync(),
    ]


def resolve_database_uri(explicit_uri=None):
    if explicit_uri:
        return normalize_database_uri(explicit_uri)
    configured = os.environ.get('YOLO_LABELING_DB_URI')
    if configured:
        return normalize_database_uri(configured)
    return None


def check_database(database_uri=None):
    resolved_uri = resolve_database_uri(database_uri)
    if not resolved_uri:
        return [_skip(
            'phase9-database',
            'no --database-uri or YOLO_LABELING_DB_URI was provided',
        )]
    engine = create_engine(resolved_uri)
    try:
        status = phase9_migration_status(engine)
    except Exception as exc:
        return [_fail('phase9-database', str(exc))]
    finally:
        engine.dispose()
    if not status['schema_ready']:
        return [_fail(
            'phase9-database',
            '; '.join(status['errors']),
        )]
    if not status['migration_recorded']:
        return [_fail(
            'phase9-database',
            'schema is ready but the Phase 9 migration ledger is missing',
        )]
    return [_pass(
        'phase9-database',
        f'schema and ledger ready ({status["migration_id"]})',
    )]


def worker_capability_errors(health):
    errors = []
    capabilities = health.get('capabilities') or {}
    if not health.get('gpu_available'):
        errors.append('GPU is not available')
    expected = {
        'optimizer_contract_version': 1,
        'training_parameter_contract_version': (
            TRAINING_PARAMETER_CONTRACT_VERSION
        ),
        'training_parameter_catalog_version': (
            TRAINING_PARAMETER_CATALOG_VERSION
        ),
        'training_parameter_catalog_hash': TRAINING_PARAMETER_CATALOG_HASH,
        'training_model_catalog_version': TRAINING_MODEL_CATALOG_VERSION,
        'training_model_catalog_hash': TRAINING_MODEL_CATALOG_HASH,
        'ultralytics_version': TRAINING_PARAMETER_ULTRALYTICS_VERSION,
    }
    for field, expected_value in expected.items():
        if capabilities.get(field) != expected_value:
            errors.append(
                f'{field} expected {expected_value!r}, '
                f'got {capabilities.get(field)!r}'
            )
    allowed_models = {
        str(item)
        for item in capabilities.get('allowed_models') or []
    }
    missing_models = sorted(
        set(ENABLED_TRAINING_MODEL_CHECKPOINTS) - allowed_models
    )
    if missing_models:
        errors.append('worker missing models: ' + ', '.join(missing_models))

    worker = SimpleNamespace(capabilities=capabilities)
    for checkpoint in ENABLED_TRAINING_MODEL_CHECKPOINTS:
        task = SimpleNamespace(
            status='queued',
            request_payload={
                'training_mode': 'fresh',
                'model': checkpoint,
                'apply_training_parameters': True,
            },
        )
        if not _worker_supports_task(worker, task):
            errors.append(
                f'scheduler rejects parameterized fresh task for {checkpoint}'
            )
    finetune_task = SimpleNamespace(
        status='queued',
        request_payload={
            'training_mode': 'finetune',
            'model': ENABLED_TRAINING_MODEL_CHECKPOINTS[0],
            'apply_training_parameters': True,
        },
    )
    if not _worker_supports_task(worker, finetune_task):
        errors.append('scheduler rejects fine-tune tasks for this worker')
    return errors


def check_worker(worker_url=None, token_env='TOOLIB_COLAB_API_TOKEN'):
    if not worker_url:
        return [_skip('worker-health', 'no --worker-url was provided')]
    token = os.environ.get(token_env)
    if not token:
        return [_fail(
            'worker-health',
            f'environment variable {token_env} is missing',
        )]
    try:
        health = ColabHttpWorkerAdapter(worker_url, token).health()
    except Exception as exc:
        return [_fail('worker-health', str(exc))]
    errors = worker_capability_errors(health)
    if errors:
        return [_fail('worker-health', '; '.join(errors))]
    return [_pass(
        'worker-health',
        f'GPU={health.get("gpu_name") or "available"}; scheduler compatible',
    )]


def readiness(results, strict=False):
    if any(result.status == 'FAIL' for result in results):
        return 'NOT READY', 1
    if strict and any(result.status == 'SKIP' for result in results):
        return 'NOT READY', 1
    return 'READY', 0


def build_parser():
    parser = argparse.ArgumentParser(
        description='Read-only ToolIbV2 training readiness preflight.',
    )
    parser.add_argument(
        '--database-uri',
        default=None,
        help='Database URI override; prefer YOLO_LABELING_DB_URI for secrets.',
    )
    parser.add_argument(
        '--worker-url',
        default=None,
        help='Optional Colab worker URL to probe.',
    )
    parser.add_argument(
        '--worker-token-env',
        default='TOOLIB_COLAB_API_TOKEN',
        help='Environment variable containing the worker bearer token.',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat skipped database or worker checks as NOT READY.',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Emit machine-readable JSON.',
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    results = [
        *run_code_checks(),
        *check_database(args.database_uri),
        *check_worker(args.worker_url, args.worker_token_env),
    ]
    summary, exit_code = readiness(results, strict=args.strict)
    if args.json:
        print(json.dumps({
            'summary': summary,
            'strict': args.strict,
            'checks': [asdict(result) for result in results],
        }, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f'[{result.status}] {result.name}: {result.detail}')
        print(summary)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
