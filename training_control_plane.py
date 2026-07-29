import csv
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from requests_toolbelt.multipart.encoder import MultipartEncoder
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from artifact_object_store import (
    ObjectStoreError,
    object_store_from_config,
)
from models import (
    db,
    AIModel,
    FineTuneParameterSet,
    ModelArtifact,
    Project,
    TrainingBatch,
    TrainingCheckpoint,
    TrainingDataset,
    TrainingJob,
    TrainingJobAttempt,
    TrainingJobEvent,
    TrainingQueueTask,
    TrainingWorker,
)
from training_dataset_service import (
    default_clear_header_callback,
    prepare_training_dataset_snapshot,
    sha256_path,
)
from training_model_catalog import (
    ENABLED_TRAINING_MODEL_CHECKPOINTS,
    ENABLED_TRAINING_MODEL_CHECKPOINT_SET,
    TRAINING_MODEL_CATALOG_HASH,
)
from training_parameter_catalog import (
    TRAINING_PARAMETER_CATALOG_HASH,
    TRAINING_PARAMETER_CATALOG_VERSION,
    TRAINING_PARAMETER_CONTRACT_VERSION,
    TRAINING_PARAMETER_DEFAULTS as FINETUNE_PARAMETER_DEFAULTS,
    TRAINING_PARAMETER_FIELDS as FINETUNE_PARAMETER_FIELDS,
    TrainingParameterCatalogError,
    normalize_training_parameters,
    parameter_option_values,
    training_parameter_catalog_payload,
)


WORKER_PROVIDERS = {'colab_http'}
WORKER_STATUSES = {'online', 'offline', 'draining', 'disabled'}
ACTIVE_TASK_STATUSES = {
    'preparing_dataset',
    'uploading_parent_model',
    'uploading_dataset',
    'submitting',
    'remote_queued',
    'remote_running',
    'downloading_artifacts',
    'importing_model',
}
DISPATCHABLE_TASK_STATUSES = {'queued', 'waiting_for_worker', 'retry_wait'}
DISPATCHABLE_TASK_STATUSES.add('resume_pending')
TERMINAL_TASK_STATUSES = {'succeeded', 'failed', 'cancelled'}
REMOTE_TERMINAL_STATUSES = {'succeeded', 'failed'}
FINETUNE_PRESET_VERSION = TRAINING_PARAMETER_CATALOG_VERSION
FINETUNE_RANKING_METRIC = 'metrics/mAP50-95(B)'
FINETUNE_ALLOWED_IMAGE_SIZES = parameter_option_values('imgsz')
FINETUNE_CACHE_MODES = parameter_option_values('cache')
FINETUNE_OPTIMIZER_MODES = parameter_option_values('optimizer_mode')
FINETUNE_EXPLICIT_OPTIMIZERS = tuple(
    optimizer
    for optimizer in parameter_option_values('optimizer')
    if optimizer != 'auto'
)
FRESH_TRAINING_MODELS = ENABLED_TRAINING_MODEL_CHECKPOINTS
OBJECT_ARTIFACT_FILENAMES = {
    'onnx': 'best.onnx',
    'pt': 'best.pt',
    'last_pt': 'last.pt',
    'manifest': 'manifest.json',
    'results': 'results.csv',
    'args': 'args.yaml',
}
DEFAULT_FINETUNE_PARAMETER_SETS = (
    {
        'system_key': 'fresh-baseline',
        'name': 'Fresh Baseline',
        'description': (
            'Full-network training from an official YOLO checkpoint.'
        ),
        'parameters': {
            **FINETUNE_PARAMETER_DEFAULTS,
            'optimizer_mode': 'explicit',
            'optimizer': 'SGD',
            'lr0': 0.01,
            'freeze': 0,
            'mosaic': 1.0,
        },
    },
    {
        'system_key': 'baseline',
        'name': 'Fine-tune Baseline',
        'description': 'Balanced starting point for a trusted detection checkpoint.',
        'parameters': {
            **FINETUNE_PARAMETER_DEFAULTS,
            'optimizer_mode': 'explicit',
            'optimizer': 'AdamW',
            'lr0': 0.0001,
        },
    },
    {
        'system_key': 'conservative-lr',
        'name': 'Conservative LR',
        'description': 'Lower learning rate to preserve more parent-model knowledge.',
        'parameters': {
            **FINETUNE_PARAMETER_DEFAULTS,
            'optimizer_mode': 'explicit',
            'optimizer': 'AdamW',
            'lr0': 0.00005,
        },
    },
    {
        'system_key': 'adaptive-lr',
        'name': 'Adaptive LR',
        'description': 'Higher learning rate for a dataset that differs from the parent.',
        'parameters': {
            **FINETUNE_PARAMETER_DEFAULTS,
            'optimizer_mode': 'explicit',
            'optimizer': 'AdamW',
            'lr0': 0.0002,
        },
    },
    {
        'system_key': 'shallow-unfreeze',
        'name': 'Shallow unfreeze',
        'description': 'Freeze fewer layers so the checkpoint can adapt more deeply.',
        'parameters': {
            **FINETUNE_PARAMETER_DEFAULTS,
            'freeze': 5,
        },
    },
    {
        'system_key': 'resolution-variant',
        'name': 'Resolution variant',
        'description': 'Use a larger image size for smaller or more distant objects.',
        'parameters': {
            **FINETUNE_PARAMETER_DEFAULTS,
            'imgsz': 768,
        },
    },
)

_executor = ThreadPoolExecutor(
    max_workers=max(int(os.environ.get('TOOLIB_TRAINING_EXECUTOR_SIZE', '8')), 1),
    thread_name_prefix='toolib-training',
)
_running_task_ids = set()
_running_task_lock = threading.Lock()
_object_store_instances = {}
_object_store_lock = threading.Lock()
_object_publish_locks = {}
_object_publish_locks_guard = threading.Lock()
_finetune_submission_locks = {}
_finetune_submission_locks_guard = threading.Lock()


class WorkerApiError(RuntimeError):
    pass


class WorkerUnavailableError(WorkerApiError):
    pass


class WorkerBusyError(WorkerApiError):
    def __init__(self, message, active_job_id=None):
        super().__init__(message)
        self.active_job_id = normalize_remote_job_id(
            active_job_id,
            required=False,
        )


class RemoteTrainingFailedError(WorkerApiError):
    pass


def utcnow():
    return datetime.utcnow()


def _normalize_finetune_submission_id(payload):
    raw_value = str(payload.get('idempotency_key') or '').strip()
    if not raw_value:
        return None
    try:
        return str(uuid.UUID(raw_value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            'idempotency_key must be a valid UUID.'
        ) from exc


@contextmanager
def _finetune_submission_guard(submission_id):
    with _finetune_submission_locks_guard:
        entry = _finetune_submission_locks.get(submission_id)
        if entry is None:
            entry = {'lock': threading.Lock(), 'users': 0}
            _finetune_submission_locks[submission_id] = entry
        entry['users'] += 1
    entry['lock'].acquire()
    advisory_connection = None
    advisory_lock_id = int.from_bytes(
        uuid.UUID(submission_id).bytes[:8],
        byteorder='big',
        signed=True,
    )
    try:
        if db.engine.dialect.name == 'postgresql':
            advisory_connection = db.engine.connect()
            advisory_connection.execute(
                text('SELECT pg_advisory_lock(:lock_id)'),
                {'lock_id': advisory_lock_id},
            )
        yield
    finally:
        if advisory_connection is not None:
            try:
                advisory_connection.execute(
                    text('SELECT pg_advisory_unlock(:lock_id)'),
                    {'lock_id': advisory_lock_id},
                )
            finally:
                advisory_connection.close()
        entry['lock'].release()
        with _finetune_submission_locks_guard:
            entry['users'] -= 1
            if (
                entry['users'] == 0
                and _finetune_submission_locks.get(submission_id) is entry
            ):
                _finetune_submission_locks.pop(submission_id, None)


@contextmanager
def _object_publish_guard(
    object_key,
    *,
    on_wait=None,
    on_heartbeat=None,
):
    with _object_publish_locks_guard:
        entry = _object_publish_locks.get(object_key)
        if entry is None:
            entry = {'lock': threading.Lock(), 'users': 0}
            _object_publish_locks[object_key] = entry
        entry['users'] += 1

    local_acquired = False
    advisory_connection = None
    advisory_acquired = False
    wait_announced = False
    advisory_lock_id = int.from_bytes(
        hashlib.blake2b(
            object_key.encode('utf-8'),
            digest_size=8,
        ).digest(),
        byteorder='big',
        signed=True,
    )

    def announce_wait():
        nonlocal wait_announced
        if not wait_announced and on_wait is not None:
            on_wait()
        wait_announced = True

    def heartbeat():
        if on_heartbeat is not None:
            on_heartbeat()

    try:
        if not entry['lock'].acquire(blocking=False):
            announce_wait()
            while not entry['lock'].acquire(timeout=5):
                heartbeat()
        local_acquired = True

        if db.engine.dialect.name == 'postgresql':
            advisory_connection = db.engine.connect()
            advisory_acquired = bool(
                advisory_connection.execute(
                    text('SELECT pg_try_advisory_lock(:lock_id)'),
                    {'lock_id': advisory_lock_id},
                ).scalar()
            )
            if not advisory_acquired:
                announce_wait()
                while not advisory_acquired:
                    time.sleep(5)
                    heartbeat()
                    advisory_acquired = bool(
                        advisory_connection.execute(
                            text('SELECT pg_try_advisory_lock(:lock_id)'),
                            {'lock_id': advisory_lock_id},
                        ).scalar()
                    )
        yield
    finally:
        if advisory_connection is not None:
            try:
                if advisory_acquired:
                    advisory_connection.execute(
                        text('SELECT pg_advisory_unlock(:lock_id)'),
                        {'lock_id': advisory_lock_id},
                    )
            finally:
                advisory_connection.close()
        if local_acquired:
            entry['lock'].release()
        with _object_publish_locks_guard:
            entry['users'] -= 1
            if (
                entry['users'] == 0
                and _object_publish_locks.get(object_key) is entry
            ):
                _object_publish_locks.pop(object_key, None)


def normalize_remote_job_id(value, *, required=True):
    normalized = str(value or '').strip()
    if not normalized:
        if required:
            raise WorkerApiError('Worker response omitted job_id.')
        return None
    try:
        return str(uuid.UUID(normalized))
    except ValueError as exc:
        raise WorkerApiError('Worker returned an invalid job_id.') from exc


def normalize_worker_api_url(value):
    raw_value = str(value or '').strip()
    if not raw_value:
        raise ValueError('api_url is required.')

    parsed = urlsplit(raw_value)
    is_local_http = (
        parsed.scheme == 'http'
        and parsed.hostname in {'localhost', '127.0.0.1'}
    )
    if parsed.scheme != 'https' and not is_local_http:
        raise ValueError('api_url must use HTTPS; HTTP is allowed only for localhost.')
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {'', '/'}
    ):
        raise ValueError('api_url must contain only the worker API origin.')

    port = f':{parsed.port}' if parsed.port else ''
    return f'{parsed.scheme}://{parsed.hostname}{port}'


def _credential_key_path():
    configured = current_app.config.get('TOOLIB_WORKER_CREDENTIAL_KEY_FILE')
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.instance_path).resolve() / 'worker_credential.key'


def _load_or_create_credential_key():
    configured_key = (
        current_app.config.get('TOOLIB_WORKER_CREDENTIAL_KEY')
        or os.environ.get('TOOLIB_WORKER_CREDENTIAL_KEY')
    )
    if configured_key:
        return str(configured_key).strip().encode('ascii')

    require_external_key = current_app.config.get(
        'TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY',
        False,
    ) or str(
        os.environ.get('TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY', '')
    ).strip().lower() in {'1', 'true', 'yes', 'on'}
    if require_external_key:
        raise RuntimeError(
            'TOOLIB_WORKER_CREDENTIAL_KEY must be configured by the secret manager.'
        )

    key_path = _credential_key_path()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.is_file():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    temporary_path = key_path.with_suffix('.tmp')
    temporary_path.write_bytes(key)
    try:
        os.chmod(temporary_path, 0o600)
    except OSError:
        pass
    temporary_path.replace(key_path)
    current_app.logger.warning(
        'Generated a local worker credential key at %s. '
        'Use TOOLIB_WORKER_CREDENTIAL_KEY from a secret manager in production.',
        key_path,
    )
    return key


def _credential_fernet():
    key = _load_or_create_credential_key()
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise RuntimeError('TOOLIB_WORKER_CREDENTIAL_KEY is not a valid Fernet key.') from exc


def encrypt_worker_token(token):
    normalized = str(token or '').strip()
    if not normalized:
        raise ValueError('api_token is required.')
    return _credential_fernet().encrypt(normalized.encode('utf-8')).decode('ascii')


def decrypt_worker_token(worker):
    try:
        return _credential_fernet().decrypt(
            worker.token_ciphertext.encode('ascii')
        ).decode('utf-8')
    except (InvalidToken, UnicodeError, AttributeError) as exc:
        raise RuntimeError(
            f'Credentials for worker {worker.worker_id} cannot be decrypted.'
        ) from exc


class LocalArtifactStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def task_directory(self, task_id):
        normalized_task_id = str(uuid.UUID(str(task_id)))
        task_root = (self.root / normalized_task_id).resolve()
        try:
            task_root.relative_to(self.root)
        except ValueError as exc:
            raise ValueError('Invalid task artifact path.') from exc
        task_root.mkdir(parents=True, exist_ok=True)
        return task_root

    def artifact_path(self, task_id, artifact_kind):
        allowed = {
            'onnx': 'best.onnx',
            'pt': 'best.pt',
            'last_pt': 'last.pt',
            'manifest': 'manifest.json',
            'results': 'results.csv',
            'args': 'args.yaml',
        }
        filename = allowed.get(artifact_kind)
        if filename is None:
            raise ValueError(f'Unsupported artifact kind: {artifact_kind}')
        return self.task_directory(task_id) / filename


def artifact_store():
    root = current_app.config.get(
        'TRAINING_ARTIFACT_ROOT',
        os.path.join(os.path.dirname(__file__), 'training_artifacts'),
    )
    return LocalArtifactStore(root)


def checkpoint_store():
    app = current_app._get_current_object()
    cache_key = (
        id(app),
        str(
            app.config.get('TOOLIB_OBJECT_STORE_BACKEND')
            or os.environ.get('TOOLIB_OBJECT_STORE_BACKEND')
            or 'disabled'
        ),
        str(
            app.config.get('TOOLIB_OBJECT_STORE_ENDPOINT')
            or os.environ.get('TOOLIB_OBJECT_STORE_ENDPOINT')
            or ''
        ),
        str(
            app.config.get('TOOLIB_OBJECT_STORE_BUCKET')
            or os.environ.get('TOOLIB_OBJECT_STORE_BUCKET')
            or ''
        ),
        str(
            app.config.get('TOOLIB_OBJECT_STORE_PREFIX')
            or os.environ.get('TOOLIB_OBJECT_STORE_PREFIX')
            or 'toolib'
        ),
    )
    with _object_store_lock:
        store = _object_store_instances.get(cache_key)
        if store is None:
            store = object_store_from_config(app.config)
            _object_store_instances[cache_key] = store
        return store


def _worker_supports_object_inputs(worker):
    return bool((worker.capabilities or {}).get('object_input_download'))


def _worker_supports_object_artifacts(worker):
    return bool((worker.capabilities or {}).get('artifact_object_upload'))


def _ensure_file_in_object_store(
    store,
    source,
    object_key,
    expected_size,
    *,
    on_wait=None,
    on_heartbeat=None,
):
    source = Path(source).resolve()
    if not source.is_file():
        raise ObjectStoreError(f'Object upload source does not exist: {source}')

    def existing_object():
        try:
            stored_object = store.head(object_key)
        except ObjectStoreError:
            return None
        if stored_object.size_bytes != int(expected_size):
            raise ObjectStoreError(
                f'Object {object_key} exists with an unexpected size.'
            )
        return stored_object

    stored = existing_object()
    if stored is not None:
        return stored, True

    with _object_publish_guard(
        object_key,
        on_wait=on_wait,
        on_heartbeat=on_heartbeat,
    ):
        stored = existing_object()
        if stored is not None:
            return stored, True
        stored = store.upload_file(source, object_key)
        if stored.size_bytes != int(expected_size):
            raise ObjectStoreError(
                f'Uploaded object {object_key} failed size verification.'
            )
        return stored, False


def _ensure_dataset_object(
    dataset,
    store,
    *,
    on_wait=None,
    on_heartbeat=None,
):
    archive_path = Path(dataset.archive_path or '').resolve()
    if not archive_path.is_file():
        raise WorkerApiError('Prepared dataset archive is missing.')
    actual_sha256 = sha256_path(archive_path)
    if actual_sha256 != dataset.archive_sha256:
        raise WorkerApiError('Prepared dataset checksum changed before storage.')
    object_key = store.object_key(
        'datasets',
        dataset.archive_sha256,
        'dataset.zip',
    )
    _stored, reused = _ensure_file_in_object_store(
        store,
        archive_path,
        object_key,
        dataset.archive_size,
        on_wait=on_wait,
        on_heartbeat=on_heartbeat,
    )
    now = utcnow()
    dataset.storage_backend = store.backend_name
    dataset.object_key = object_key
    dataset.object_uploaded_at = dataset.object_uploaded_at or now
    dataset.object_verified_at = now
    return object_key, reused


def _ensure_parent_object(artifact, store):
    artifact_path = Path(artifact.storage_path or '').resolve()
    if not artifact_path.is_file():
        raise WorkerApiError('Parent model artifact is missing.')
    actual_sha256 = sha256_path(artifact_path)
    if actual_sha256 != artifact.sha256:
        raise WorkerApiError('Parent model checksum changed before storage.')
    object_key = store.object_key(
        'parents',
        artifact.sha256,
        'parent.pt',
    )
    _ensure_file_in_object_store(
        store,
        artifact_path,
        object_key,
        artifact.size_bytes,
    )
    artifact.storage_backend = store.backend_name
    artifact.object_key = object_key
    artifact.object_verified_at = utcnow()
    return object_key


def _object_download_payload(store, *, object_key, sha256, size_bytes):
    return {
        'object_key': object_key,
        'sha256': sha256,
        'size_bytes': int(size_bytes),
        'download_url': store.presign_download(object_key),
    }


def _artifact_object_key(store, task, attempt, artifact_kind):
    filename = OBJECT_ARTIFACT_FILENAMES[artifact_kind]
    return store.object_key(
        'artifacts',
        task.task_id,
        f'generation-{attempt.generation}',
        filename,
    )


def _artifact_upload_targets(store, task, attempt):
    return [
        {
            'kind': artifact_kind,
            'object_key': _artifact_object_key(
                store,
                task,
                attempt,
                artifact_kind,
            ),
            'upload_url': store.presign_upload(
                _artifact_object_key(
                    store,
                    task,
                    attempt,
                    artifact_kind,
                )
            ),
        }
        for artifact_kind in OBJECT_ARTIFACT_FILENAMES
    ]


class ColabHttpWorkerAdapter:
    provider = 'colab_http'

    def __init__(self, api_url, api_token, session=None):
        self.api_url = normalize_worker_api_url(api_url)
        self.api_token = str(api_token or '').strip()
        if not self.api_token:
            raise ValueError('api_token is required.')
        self.session = session or requests.Session()

    def _headers(self, accept='application/json'):
        return {
            'Accept': accept,
            'Authorization': f'Bearer {self.api_token}',
        }

    @staticmethod
    def _response_payload(response):
        try:
            payload = response.json()
        except ValueError:
            payload = {'detail': response.text[:2000]}
        return payload if isinstance(payload, dict) else {
            'detail': 'Worker returned an invalid JSON response.'
        }

    def _require_success(self, response, operation):
        payload = self._response_payload(response)
        if not 200 <= response.status_code < 300:
            detail = payload.get('detail') or payload.get('error') or 'Unknown error'
            raise WorkerApiError(
                f'{operation} returned HTTP {response.status_code}: {detail}'
            )
        return payload

    def health(self):
        try:
            response = self.session.get(
                f'{self.api_url}/health',
                headers=self._headers(),
                timeout=(10, 30),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise WorkerUnavailableError(f'Worker health request failed: {exc}') from exc
        payload = self._require_success(response, 'Worker health')
        return {
            'status': payload.get('status') or 'online',
            'gpu_available': bool(payload.get('gpu_available')),
            'gpu_name': payload.get('gpu_name'),
            'active_job_id': payload.get('active_job_id'),
            'capabilities': payload.get('capabilities') or {
                'dataset_upload': True,
                'training': True,
                'artifact_download': ['onnx'],
                'training_modes': ['fresh'],
                'model_artifact_upload': False,
                'max_concurrent_jobs': 1,
                'idempotent_submit': bool(payload.get('idempotent_submit', False)),
            },
        }

    def upload_model_artifact(self, artifact):
        artifact_path = Path(artifact.storage_path or '').resolve()
        if not artifact_path.is_file():
            raise WorkerApiError('Parent model artifact is missing.')
        if sha256_path(artifact_path) != artifact.sha256:
            raise WorkerApiError('Parent model checksum changed before upload.')

        try:
            cache_response = self.session.get(
                f'{self.api_url}/api/model-artifacts/{artifact.artifact_id}',
                headers=self._headers(),
                params={'sha256': artifact.sha256},
                timeout=(10, 60),
                allow_redirects=False,
            )
            if cache_response.status_code == 200:
                payload = self._require_success(
                    cache_response,
                    'Parent model cache lookup',
                )
                if (
                    payload.get('artifact_id') == artifact.artifact_id
                    and payload.get('sha256') == artifact.sha256
                ):
                    return payload
                raise WorkerApiError(
                    'Worker model cache returned different identity metadata.'
                )
            if cache_response.status_code != 404:
                self._require_success(
                    cache_response,
                    'Parent model cache lookup',
                )

            with artifact_path.open('rb') as artifact_stream:
                multipart_body = MultipartEncoder(fields={
                    'artifact_id': artifact.artifact_id,
                    'sha256': artifact.sha256,
                    'artifact': (
                        f'{artifact.artifact_id}.pt',
                        artifact_stream,
                        'application/octet-stream',
                    ),
                })
                headers = self._headers()
                headers['Content-Type'] = multipart_body.content_type
                response = self.session.post(
                    f'{self.api_url}/api/model-artifacts',
                    headers=headers,
                    data=multipart_body,
                    timeout=(15, 3600),
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            raise WorkerUnavailableError(
                f'Parent model upload failed: {exc}'
            ) from exc

        payload = self._require_success(response, 'Parent model upload')
        if payload.get('artifact_id') != artifact.artifact_id:
            raise WorkerApiError('Worker returned a different artifact_id.')
        if payload.get('sha256') != artifact.sha256:
            raise WorkerApiError('Worker returned a different model checksum.')
        if payload.get('task') != 'detect':
            raise WorkerApiError('Only YOLO detection checkpoints are supported.')
        return payload

    def resolve_model_artifact(self, artifact, object_payload):
        payload = {
            'artifact_id': artifact.artifact_id,
            **object_payload,
        }
        try:
            response = self.session.post(
                f'{self.api_url}/api/model-artifacts/resolve',
                headers=self._headers(),
                json=payload,
                timeout=(15, 1800),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise WorkerUnavailableError(
                f'Parent model object resolution failed: {exc}'
            ) from exc
        resolved = self._require_success(
            response,
            'Parent model object resolution',
        )
        if resolved.get('artifact_id') != artifact.artifact_id:
            raise WorkerApiError('Worker returned a different artifact_id.')
        if resolved.get('sha256') != artifact.sha256:
            raise WorkerApiError('Worker returned a different model checksum.')
        if resolved.get('task') != 'detect':
            raise WorkerApiError('Only YOLO detection checkpoints are supported.')
        return resolved

    def upload_dataset(self, dataset):
        archive_path = Path(dataset.archive_path or '').resolve()
        if not archive_path.is_file():
            raise WorkerApiError('Prepared dataset archive is missing.')
        if sha256_path(archive_path) != dataset.archive_sha256:
            raise WorkerApiError('Prepared dataset checksum changed before upload.')

        try:
            with archive_path.open('rb') as archive_stream:
                multipart_body = MultipartEncoder(fields={
                    'dataset_id': dataset.dataset_id,
                    'sha256': dataset.archive_sha256,
                    'archive': (
                        f'{dataset.dataset_id}.zip',
                        archive_stream,
                        'application/zip',
                    ),
                })
                headers = self._headers()
                headers['Content-Type'] = multipart_body.content_type
                response = self.session.post(
                    f'{self.api_url}/api/datasets',
                    headers=headers,
                    data=multipart_body,
                    timeout=(15, 3600),
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            raise WorkerUnavailableError(f'Dataset upload failed: {exc}') from exc

        payload = self._require_success(response, 'Dataset upload')
        if payload.get('dataset_id') != dataset.dataset_id:
            raise WorkerApiError('Worker returned a different dataset_id.')
        if payload.get('sha256') != dataset.archive_sha256:
            raise WorkerApiError('Worker returned a different dataset checksum.')
        return payload

    def submit_job(self, request_payload, idempotency_key):
        payload = dict(request_payload)
        payload['idempotency_key'] = idempotency_key
        headers = self._headers()
        headers['Idempotency-Key'] = idempotency_key
        try:
            response = self.session.post(
                f'{self.api_url}/api/train',
                headers=headers,
                json=payload,
                timeout=(15, 90),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise WorkerUnavailableError(f'Training submission failed: {exc}') from exc
        response_payload = self._response_payload(response)
        if response.status_code == 409:
            detail = response_payload.get('detail')
            if isinstance(detail, dict):
                active_job_id = detail.get('active_job_id')
                detail_message = (
                    detail.get('message')
                    or detail.get('error')
                    or str(detail)
                )
            else:
                active_job_id = response_payload.get('active_job_id')
                detail_message = (
                    detail
                    or response_payload.get('message')
                    or response_payload.get('error')
                    or 'Worker is already running another training job.'
                )
            raise WorkerBusyError(
                f'Training submission returned HTTP 409: {detail_message}',
                active_job_id=active_job_id,
            )
        if not 200 <= response.status_code < 300:
            return self._require_success(response, 'Training submission')
        return response_payload

    def get_job(self, remote_job_id):
        try:
            response = self.session.get(
                f'{self.api_url}/api/jobs/{remote_job_id}',
                headers=self._headers(),
                timeout=(10, 60),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise WorkerUnavailableError(f'Training status request failed: {exc}') from exc
        return self._require_success(response, 'Training status')

    def download_artifact(
        self,
        remote_job_id,
        artifact_kind,
        destination,
        progress_callback=None,
    ):
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_name(
            f'.{destination.name}.{os.getpid()}.'
            f'{threading.get_ident()}.{uuid.uuid4().hex}.part'
        )
        try:
            with self.session.get(
                f'{self.api_url}/api/jobs/{remote_job_id}/artifacts/{artifact_kind}',
                headers=self._headers('application/octet-stream'),
                timeout=(15, 3600),
                allow_redirects=False,
                stream=True,
            ) as response:
                if not 200 <= response.status_code < 300:
                    self._require_success(response, f'{artifact_kind} artifact download')
                try:
                    total_bytes = int(response.headers.get('Content-Length') or 0)
                except (TypeError, ValueError):
                    total_bytes = 0
                downloaded_bytes = 0
                if progress_callback is not None:
                    progress_callback(downloaded_bytes, total_bytes)
                with temporary_path.open('wb') as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
                            downloaded_bytes += len(chunk)
                            if progress_callback is not None:
                                progress_callback(downloaded_bytes, total_bytes)
            temporary_path.replace(destination)
        except requests.RequestException as exc:
            temporary_path.unlink(missing_ok=True)
            raise WorkerUnavailableError(
                f'{artifact_kind} artifact download failed: {exc}'
            ) from exc
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return destination


def adapter_for_worker(worker, session=None):
    if worker.provider != 'colab_http':
        raise ValueError(f'Unsupported training worker provider: {worker.provider}')
    return ColabHttpWorkerAdapter(
        worker.api_url,
        decrypt_worker_token(worker),
        session=session,
    )


def _active_lease_count(worker_id):
    now = utcnow()
    return TrainingQueueTask.query.filter(
        TrainingQueueTask.assigned_worker_id == worker_id,
        TrainingQueueTask.status.in_(ACTIVE_TASK_STATUSES | {'worker_lost'}),
        db.or_(
            TrainingQueueTask.lease_expires_at.is_(None),
            TrainingQueueTask.lease_expires_at > now,
            TrainingQueueTask.status == 'worker_lost',
        ),
    ).count()


def serialize_worker(worker):
    return worker.to_dict(active_leases=_active_lease_count(worker.id))


def record_task_event(
    task,
    event_type,
    *,
    from_status=None,
    to_status=None,
    message=None,
    details=None,
    attempt=None,
):
    event = TrainingJobEvent(
        task_id=task.id,
        attempt_id=attempt.id if attempt is not None else None,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=str(message or '')[:8000] or None,
        details=details or None,
    )
    db.session.add(event)
    return event


def transition_task(
    task,
    status,
    stage,
    message,
    *,
    attempt=None,
    details=None,
):
    previous_status = task.status
    task.status = status
    task.stage = stage
    task.message = str(message or '')[:4000] or None
    task.updated_at = utcnow()
    if task.started_at is None and status in ACTIVE_TASK_STATUSES:
        task.started_at = utcnow()
    if status in TERMINAL_TASK_STATUSES:
        task.finished_at = utcnow()
        task.lease_token = None
        task.lease_expires_at = None
    record_task_event(
        task,
        'status_changed',
        from_status=previous_status,
        to_status=status,
        message=message,
        details=details,
        attempt=attempt,
    )


def refresh_batch_status(batch_id):
    batch = db.session.get(TrainingBatch, batch_id)
    if batch is None:
        return None
    tasks = TrainingQueueTask.query.filter_by(batch_id=batch.id).all()
    batch.total_jobs = len(tasks)
    batch.succeeded_jobs = sum(task.status == 'succeeded' for task in tasks)
    batch.failed_jobs = sum(task.status == 'failed' for task in tasks)
    batch.cancelled_jobs = sum(task.status == 'cancelled' for task in tasks)
    terminal_count = batch.succeeded_jobs + batch.failed_jobs + batch.cancelled_jobs

    if not tasks:
        batch.status = 'queued'
    elif terminal_count == len(tasks):
        batch.finished_at = batch.finished_at or utcnow()
        if batch.succeeded_jobs == len(tasks):
            batch.status = 'succeeded'
        elif batch.failed_jobs == len(tasks):
            batch.status = 'failed'
        elif batch.cancelled_jobs == len(tasks):
            batch.status = 'cancelled'
        else:
            batch.status = 'partial_failed'
    elif any(task.status in ACTIVE_TASK_STATUSES | {'worker_lost'} for task in tasks):
        batch.status = 'running'
        batch.started_at = batch.started_at or utcnow()
        batch.finished_at = None
    else:
        batch.status = 'queued'
        batch.finished_at = None
    return batch


def probe_worker(worker, session=None):
    if not worker.enabled:
        worker.status = 'disabled'
        worker.last_error = None
        return serialize_worker(worker)

    try:
        health = adapter_for_worker(worker, session=session).health()
        worker.status = 'online'
        worker.gpu_available = bool(health.get('gpu_available'))
        worker.gpu_name = str(health.get('gpu_name') or '')[:200] or None
        worker.remote_active_job_id = normalize_remote_job_id(
            health.get('active_job_id'),
            required=False,
        )
        worker.capabilities = health.get('capabilities') or {}
        worker.last_heartbeat_at = utcnow()
        worker.last_error = None
    except Exception as exc:
        worker.status = 'offline'
        worker.last_error = str(exc)[:4000]
    worker.updated_at = utcnow()
    db.session.commit()
    return serialize_worker(worker)


def probe_all_workers():
    workers = TrainingWorker.query.filter_by(enabled=True).all()
    for worker in workers:
        probe_worker(worker)
    return workers


def _normalize_finetune_parameters(raw_job):
    if not isinstance(raw_job, dict):
        raise ValueError('Fine-tune parameters must be a JSON object.')
    supplied_parameters = {
        name: raw_job[name]
        for name in FINETUNE_PARAMETER_FIELDS
        if name in raw_job
    }
    try:
        parameters = normalize_training_parameters(supplied_parameters)
    except TrainingParameterCatalogError as exc:
        raise ValueError(f'Fine-tune {exc}') from exc

    if parameters['optimizer_mode'] == 'auto':
        parameters['optimizer'] = 'auto'
        parameters['lr0'] = None
    else:
        if parameters['optimizer'] == 'auto':
            raise ValueError(
                'Fine-tune explicit optimizer requires a named optimizer.'
            )
        if parameters['lr0'] is None:
            raise ValueError('Fine-tune explicit optimizer requires lr0.')
    return {
        name: parameters[name]
        for name in FINETUNE_PARAMETER_FIELDS
        if name not in {'epochs', 'batch', 'imgsz'}
    }


def normalize_finetune_parameter_set_parameters(raw_parameters):
    if not isinstance(raw_parameters, dict):
        raise ValueError('parameters must be a JSON object.')
    try:
        normalized = normalize_training_parameters(raw_parameters)
    except TrainingParameterCatalogError as exc:
        raise ValueError(str(exc)) from exc
    normalized.update(_normalize_finetune_parameters(normalized))
    normalized['close_mosaic'] = min(
        normalized['close_mosaic'],
        max(normalized['epochs'] - 1, 0),
    )
    return normalized


def _normalize_parameter_set_name(value):
    name = str(value or '').strip()
    if not name:
        raise ValueError('Parameter-set name must not be empty.')
    if len(name) > 120:
        raise ValueError('Parameter-set name must contain at most 120 characters.')
    return name


def _active_parameter_set_name_exists(name, exclude_id=None):
    query = FineTuneParameterSet.query.filter(
        FineTuneParameterSet.is_active.is_(True),
        db.func.lower(FineTuneParameterSet.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.filter(FineTuneParameterSet.id != int(exclude_id))
    return query.first() is not None


def finetune_parameter_set_usage_count(parameter_set_id):
    return TrainingQueueTask.query.filter_by(
        parameter_set_id=int(parameter_set_id)
    ).count()


def serialize_finetune_parameter_set(parameter_set):
    payload = parameter_set.to_dict(
        usage_count=finetune_parameter_set_usage_count(parameter_set.id)
    )
    payload['parameters'] = normalize_finetune_parameter_set_parameters(
        parameter_set.parameters or {}
    )
    return payload


def ensure_default_finetune_parameter_sets():
    existing_keys = {
        system_key
        for (system_key,) in db.session.query(
            FineTuneParameterSet.system_key
        ).filter(
            FineTuneParameterSet.system_key.isnot(None)
        ).all()
    }
    created = False
    for default in DEFAULT_FINETUNE_PARAMETER_SETS:
        if default['system_key'] in existing_keys:
            continue
        db.session.add(FineTuneParameterSet(
            preset_id=str(uuid.uuid4()),
            system_key=default['system_key'],
            name=default['name'],
            description=default['description'],
            model_task='detect',
            parameters=normalize_finetune_parameter_set_parameters(
                default['parameters']
            ),
            version=1,
            is_system=True,
            is_active=True,
        ))
        created = True
    if created:
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            missing = [
                default['system_key']
                for default in DEFAULT_FINETUNE_PARAMETER_SETS
                if FineTuneParameterSet.query.filter_by(
                    system_key=default['system_key']
                ).first() is None
            ]
            if missing:
                raise
    return FineTuneParameterSet.query.order_by(
        FineTuneParameterSet.is_active.desc(),
        FineTuneParameterSet.is_system.desc(),
        FineTuneParameterSet.id.asc(),
    ).all()


def list_finetune_parameter_sets(include_archived=False):
    ensure_default_finetune_parameter_sets()
    query = FineTuneParameterSet.query
    if not include_archived:
        query = query.filter(FineTuneParameterSet.is_active.is_(True))
    return [
        serialize_finetune_parameter_set(parameter_set)
        for parameter_set in query.order_by(
            FineTuneParameterSet.is_active.desc(),
            FineTuneParameterSet.is_system.desc(),
            FineTuneParameterSet.name.asc(),
            FineTuneParameterSet.id.asc(),
        ).all()
    ]


def create_finetune_parameter_set(payload):
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')
    name = _normalize_parameter_set_name(payload.get('name'))
    if _active_parameter_set_name_exists(name):
        raise ValueError('An active parameter set already uses this name.')
    description = str(payload.get('description') or '').strip()
    if len(description) > 500:
        raise ValueError('description must contain at most 500 characters.')
    parameter_set = FineTuneParameterSet(
        preset_id=str(uuid.uuid4()),
        name=name,
        description=description or None,
        model_task='detect',
        parameters=normalize_finetune_parameter_set_parameters(
            payload.get('parameters') or {}
        ),
        version=1,
        is_system=False,
        is_active=True,
    )
    db.session.add(parameter_set)
    db.session.commit()
    return parameter_set


def update_finetune_parameter_set(parameter_set, payload):
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')
    name = _normalize_parameter_set_name(
        payload.get('name', parameter_set.name)
    )
    if (
        parameter_set.is_active
        and _active_parameter_set_name_exists(
            name,
            exclude_id=parameter_set.id,
        )
    ):
        raise ValueError('An active parameter set already uses this name.')
    description = str(
        payload.get('description', parameter_set.description or '') or ''
    ).strip()
    if len(description) > 500:
        raise ValueError('description must contain at most 500 characters.')
    raw_parameters = payload.get('parameters')
    if raw_parameters is None:
        raw_parameters = parameter_set.parameters or {}
    elif isinstance(raw_parameters, dict):
        raw_parameters = {
            **(parameter_set.parameters or {}),
            **raw_parameters,
        }
    parameters = normalize_finetune_parameter_set_parameters(raw_parameters)
    changed = (
        name != parameter_set.name
        or (description or None) != parameter_set.description
        or parameters != (parameter_set.parameters or {})
    )
    if changed:
        parameter_set.name = name
        parameter_set.description = description or None
        parameter_set.parameters = parameters
        parameter_set.version += 1
        parameter_set.updated_at = utcnow()
        db.session.commit()
    return parameter_set


def clone_finetune_parameter_set(parameter_set, payload=None):
    payload = payload or {}
    base_name = _normalize_parameter_set_name(
        payload.get('name') or f'{parameter_set.name} copy'
    )
    name = base_name
    suffix = 2
    while _active_parameter_set_name_exists(name):
        suffix_text = f' {suffix}'
        name = f'{base_name[:120 - len(suffix_text)]}{suffix_text}'
        suffix += 1
    return create_finetune_parameter_set({
        'name': name,
        'description': payload.get(
            'description',
            parameter_set.description or '',
        ),
        'parameters': payload.get(
            'parameters',
            parameter_set.parameters or {},
        ),
    })


def set_finetune_parameter_set_active(parameter_set, is_active):
    is_active = bool(is_active)
    if is_active and _active_parameter_set_name_exists(
        parameter_set.name,
        exclude_id=parameter_set.id,
    ):
        raise ValueError(
            'Another active parameter set already uses this name.'
        )
    parameter_set.is_active = is_active
    parameter_set.archived_at = None if is_active else utcnow()
    parameter_set.updated_at = utcnow()
    db.session.commit()
    return parameter_set


def delete_finetune_parameter_set(parameter_set):
    usage_count = finetune_parameter_set_usage_count(parameter_set.id)
    if parameter_set.is_system:
        raise ValueError(
            'System parameter sets cannot be deleted; archive them instead.'
        )
    if usage_count:
        raise ValueError(
            'Parameter sets with training history cannot be deleted; '
            'archive them instead.'
        )
    db.session.delete(parameter_set)
    db.session.commit()


def create_training_batch(payload):
    jobs_payload = payload.get('jobs')
    if not isinstance(jobs_payload, list) or not jobs_payload:
        raise ValueError('jobs must be a non-empty JSON array.')
    if len(jobs_payload) > 100:
        raise ValueError('A training batch can contain at most 100 jobs.')

    supplied_batch_id = str(payload.get('batch_id') or '').strip()
    if supplied_batch_id:
        try:
            batch_uuid = str(uuid.UUID(supplied_batch_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('batch_id must be a valid UUID.') from exc
    else:
        batch_uuid = str(uuid.uuid4())

    name = str(payload.get('name') or '').strip()
    if not name:
        name = f'Training batch {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    max_attempts_default = int(payload.get('max_attempts') or 3)
    if not 1 <= max_attempts_default <= 10:
        raise ValueError('max_attempts must be between 1 and 10.')
    max_resume_count_default = int(
        payload.get('max_resume_count')
        if payload.get('max_resume_count') is not None
        else 3
    )
    if not 0 <= max_resume_count_default <= 10:
        raise ValueError('max_resume_count must be between 0 and 10.')
    checkpoint_interval_default = int(
        payload.get('checkpoint_interval') or 5
    )
    if not 5 <= checkpoint_interval_default <= 100:
        raise ValueError('checkpoint_interval must be between 5 and 100.')

    experiment_type = str(
        payload.get('experiment_type') or 'fresh'
    ).strip().lower()
    if experiment_type not in {'fresh', 'finetune_sweep'}:
        raise ValueError('experiment_type must be fresh or finetune_sweep.')

    batch_parent_model_id = payload.get('parent_model_id')
    if batch_parent_model_id is not None:
        try:
            batch_parent_model_id = int(batch_parent_model_id)
        except (TypeError, ValueError) as exc:
            raise ValueError('parent_model_id must be an integer.') from exc
        if db.session.get(AIModel, batch_parent_model_id) is None:
            raise ValueError('parent_model_id does not exist.')

    batch_training_dataset_id = payload.get('training_dataset_id')
    if batch_training_dataset_id is not None:
        try:
            batch_training_dataset_id = int(batch_training_dataset_id)
        except (TypeError, ValueError) as exc:
            raise ValueError('training_dataset_id must be an integer.') from exc
        if db.session.get(TrainingDataset, batch_training_dataset_id) is None:
            raise ValueError('training_dataset_id does not exist.')

    batch = TrainingBatch(
        batch_id=batch_uuid,
        name=name[:160],
        status='queued',
        experiment_type=experiment_type,
        parent_model_id=batch_parent_model_id,
        training_dataset_id=batch_training_dataset_id,
        preset_version=(
            str(payload.get('preset_version') or '')[:50] or None
        ),
        ranking_metric=(
            str(payload.get('ranking_metric') or FINETUNE_RANKING_METRIC)[:80]
        ),
        total_jobs=len(jobs_payload),
    )
    db.session.add(batch)
    db.session.flush()

    seen_idempotency_keys = set()
    tasks = []
    for index, raw_job in enumerate(jobs_payload):
        if not isinstance(raw_job, dict):
            raise ValueError(f'jobs[{index}] must be a JSON object.')
        try:
            project_id = int(raw_job.get('project_id'))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'jobs[{index}].project_id must be an integer.') from exc
        if db.session.get(Project, project_id) is None:
            raise ValueError(f'jobs[{index}].project_id does not exist.')

        training_mode = str(
            raw_job.get('training_mode')
            or ('finetune' if experiment_type == 'finetune_sweep' else 'fresh')
        ).strip().lower()
        if training_mode not in {'fresh', 'finetune'}:
            raise ValueError(
                f'jobs[{index}].training_mode must be fresh or finetune.'
            )

        parameter_set = None
        parameter_set_parameters = None
        parameter_set_id = raw_job.get('parameter_set_id')
        if parameter_set_id is not None:
            try:
                parameter_set_id = int(parameter_set_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f'jobs[{index}].parameter_set_id must be an integer.'
                ) from exc
            parameter_set = db.session.get(
                FineTuneParameterSet,
                parameter_set_id,
            )
            if parameter_set is None:
                raise ValueError(
                    f'jobs[{index}].parameter_set_id does not exist.'
                )
            if not parameter_set.is_active:
                raise ValueError(
                    f'jobs[{index}].parameter_set_id is archived.'
                )
            if parameter_set.model_task != 'detect':
                raise ValueError(
                    f'jobs[{index}].parameter_set_id must target detection.'
                )
            parameter_set_parameters = (
                normalize_finetune_parameter_set_parameters(
                    parameter_set.parameters or {}
                )
            )

        parent_model_id = raw_job.get(
            'parent_model_id',
            batch_parent_model_id,
        )
        parent_model = None
        parent_artifact = None
        if training_mode == 'finetune':
            try:
                parent_model_id = int(parent_model_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f'jobs[{index}].parent_model_id must be an integer.'
                ) from exc
            parent_model = db.session.get(AIModel, parent_model_id)
            if parent_model is None:
                raise ValueError(
                    f'jobs[{index}].parent_model_id does not exist.'
                )
            if (
                parent_model.model_type != 'detection'
                or parent_model.finetune_status != 'ready'
            ):
                raise ValueError(
                    f'jobs[{index}] parent model is not ready for fine-tune.'
                )
            parent_artifact = ModelArtifact.query.filter_by(
                model_id=parent_model.id,
                kind='parent_pt',
            ).first()
            if parent_artifact is None:
                parent_artifact = ModelArtifact.query.filter_by(
                    model_id=parent_model.id,
                    kind='best_pt',
                ).first()
            if parent_artifact is None:
                raise ValueError(
                    f'jobs[{index}] parent model has no trainable .pt artifact.'
                )
        else:
            parent_model_id = None

        model = str(
            raw_job.get('model')
            or (parent_model.filename if parent_model else 'yolo11s.pt')
        ).strip()
        if (
            training_mode == 'fresh'
            and model not in ENABLED_TRAINING_MODEL_CHECKPOINT_SET
        ):
            raise ValueError(
                f'jobs[{index}].model must be one of '
                f'{", ".join(FRESH_TRAINING_MODELS)}.'
            )
        effective_parameters = parameter_set_parameters or raw_job
        epochs = int(effective_parameters.get('epochs') or 1)
        batch_size = int(effective_parameters.get('batch') or 16)
        imgsz = int(effective_parameters.get('imgsz') or 640)
        if epochs < 1 or batch_size < 1 or imgsz < 32:
            raise ValueError(
                f'jobs[{index}] requires epochs>=1, batch>=1 and imgsz>=32.'
            )

        splits = raw_job.get('splits') or {'train': 80, 'val': 20, 'test': 0}
        if not isinstance(splits, dict):
            raise ValueError(f'jobs[{index}].splits must be a JSON object.')
        normalized_splits = {
            split: int(splits.get(split, 0) or 0)
            for split in ('train', 'val', 'test')
        }
        if (
            sum(normalized_splits.values()) != 100
            or normalized_splits['train'] <= 0
            or normalized_splits['val'] <= 0
        ):
            raise ValueError(
                f'jobs[{index}].splits must total 100 with non-zero train and val.'
            )

        include_unlabeled = raw_job.get('include_unlabeled', False)
        exclude_flagged = raw_job.get('exclude_flagged', True)
        if not isinstance(include_unlabeled, bool) or not isinstance(exclude_flagged, bool):
            raise ValueError(
                f'jobs[{index}] include_unlabeled/exclude_flagged must be booleans.'
            )

        task_uuid = str(uuid.uuid4())
        supplied_key = str(raw_job.get('idempotency_key') or '').strip()
        idempotency_key = supplied_key or f'{batch.batch_id}:{project_id}:{index}'
        if len(idempotency_key) > 100:
            raise ValueError(
                f'jobs[{index}].idempotency_key must contain at most 100 characters.'
            )
        if idempotency_key in seen_idempotency_keys:
            raise ValueError(f'Duplicate idempotency_key in jobs[{index}].')
        seen_idempotency_keys.add(idempotency_key)
        if TrainingQueueTask.query.filter_by(idempotency_key=idempotency_key).first():
            raise ValueError(f'idempotency_key already exists: {idempotency_key}')

        max_attempts = int(raw_job.get('max_attempts') or max_attempts_default)
        if not 1 <= max_attempts <= 10:
            raise ValueError(f'jobs[{index}].max_attempts must be between 1 and 10.')
        max_resume_count = int(
            raw_job.get('max_resume_count')
            if raw_job.get('max_resume_count') is not None
            else max_resume_count_default
        )
        if not 0 <= max_resume_count <= 10:
            raise ValueError(
                f'jobs[{index}].max_resume_count must be between 0 and 10.'
            )
        checkpoint_interval = int(
            raw_job.get('checkpoint_interval')
            or checkpoint_interval_default
        )
        if not 5 <= checkpoint_interval <= 100:
            raise ValueError(
                f'jobs[{index}].checkpoint_interval must be between 5 and 100.'
            )

        training_dataset_id = raw_job.get(
            'training_dataset_id',
            batch_training_dataset_id,
        )
        training_dataset = None
        if training_dataset_id is not None:
            try:
                training_dataset_id = int(training_dataset_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f'jobs[{index}].training_dataset_id must be an integer.'
                ) from exc
            training_dataset = db.session.get(
                TrainingDataset,
                training_dataset_id,
            )
            if training_dataset is None:
                raise ValueError(
                    f'jobs[{index}].training_dataset_id does not exist.'
                )
            if training_dataset.project_id != project_id:
                raise ValueError(
                    f'jobs[{index}] dataset does not belong to project_id.'
                )

        request_payload = {
            'training_mode': training_mode,
            'model': model[:100],
            'epochs': epochs,
            'batch': batch_size,
            'imgsz': imgsz,
            'optimizer_mode': 'auto',
            'optimizer': 'auto',
            'lr0': None,
            'apply_training_parameters': bool(
                training_mode == 'finetune' or parameter_set is not None
            ),
        }
        parameter_set_snapshot = None
        if training_mode == 'finetune' or parameter_set is not None:
            request_payload.update(_normalize_finetune_parameters(
                parameter_set_parameters or raw_job
            ))
        if training_mode == 'finetune':
            request_payload.update({
                'parent_artifact_id': parent_artifact.artifact_id,
                'parent_sha256': parent_artifact.sha256,
            })
        if parameter_set is not None:
            parameter_set_snapshot = {
                'id': parameter_set.id,
                'preset_id': parameter_set.preset_id,
                'name': parameter_set.name,
                'version': parameter_set.version,
                'parameters': {
                    field: request_payload[field]
                    for field in FINETUNE_PARAMETER_FIELDS
                },
            }
        config_hash = hashlib.sha256(
            json.dumps(
                request_payload,
                sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')
        ).hexdigest()

        task = TrainingQueueTask(
            task_id=task_uuid,
            idempotency_key=idempotency_key,
            batch_id=batch.id,
            project_id=project_id,
            training_dataset_id=(
                training_dataset.id if training_dataset else None
            ),
            parent_model_id=parent_model_id,
            parameter_set_id=(
                parameter_set.id if parameter_set is not None else None
            ),
            parameter_set_snapshot=parameter_set_snapshot,
            candidate_name=(
                str(raw_job.get('candidate_name') or '')[:100] or None
            ),
            config_hash=config_hash,
            status='queued',
            stage='queued',
            priority=int(raw_job.get('priority') or 0),
            request_payload=request_payload,
            dataset_config={
                'splits': normalized_splits,
                'include_unlabeled': include_unlabeled,
                'exclude_flagged': exclude_flagged,
            },
            max_attempts=max_attempts,
            max_resume_count=max_resume_count,
            checkpoint_interval=checkpoint_interval,
            message='Waiting for scheduler.',
        )
        db.session.add(task)
        db.session.flush()
        record_task_event(
            task,
            'task_created',
            to_status='queued',
            message='Training task created.',
            details={'batch_id': batch.batch_id, 'project_id': project_id},
        )
        tasks.append(task)

    db.session.commit()
    return batch, tasks


def _canonical_class_names(value):
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        def sort_key(item):
            key = str(item[0])
            return (0, int(key)) if key.isdigit() else (1, key)

        return [
            str(class_name)
            for _key, class_name in sorted(value.items(), key=sort_key)
        ]
    return []


def parent_artifact_for_model(model):
    artifact = ModelArtifact.query.filter_by(
        model_id=model.id,
        kind='parent_pt',
    ).first()
    if artifact is None:
        artifact = ModelArtifact.query.filter_by(
            model_id=model.id,
            kind='best_pt',
        ).first()
    return artifact


def worker_supports_finetune(worker):
    capabilities = worker.capabilities or {}
    training_modes = capabilities.get('training_modes') or ['fresh']
    return (
        bool(capabilities.get('model_artifact_upload'))
        and 'finetune' in training_modes
    )


def validate_parent_model(model, worker, adapter_factory=adapter_for_worker):
    if model.model_type != 'detection':
        raise ValueError('Only detection checkpoints can be fine-tuned.')
    artifact = parent_artifact_for_model(model)
    if artifact is None:
        raise ValueError('Model has no trainable .pt artifact.')
    if not worker.enabled or worker.status != 'online':
        raise ValueError('Selected validation worker is not online.')
    if not worker_supports_finetune(worker):
        raise ValueError(
            'Selected worker does not advertise Phase 6 fine-tune support.'
        )

    adapter = adapter_factory(worker)
    store = checkpoint_store()
    if store.enabled and _worker_supports_object_inputs(worker):
        _ensure_parent_object(artifact, store)
        db.session.commit()
        payload = adapter.resolve_model_artifact(
            artifact,
            _object_download_payload(
                store,
                object_key=artifact.object_key,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
            ),
        )
    else:
        payload = adapter.upload_model_artifact(artifact)
    class_names = _canonical_class_names(payload.get('class_names'))
    if not class_names:
        raise WorkerApiError(
            'Worker could not read class names from the checkpoint.'
        )
    model.class_names = class_names
    model.finetune_status = 'ready'
    model.validation_error = None
    model.validated_at = utcnow()
    artifact.metadata_json = {
        **(artifact.metadata_json or {}),
        'task': payload.get('task'),
        'class_names': class_names,
        'validated_worker_id': worker.worker_id,
        'validated_at': model.validated_at.isoformat(),
    }
    db.session.commit()
    return payload


def finetune_presets_payload(include_archived=False):
    return {
        'version': FINETUNE_PRESET_VERSION,
        'parameter_catalog': training_parameter_catalog_payload(),
        'parameter_catalog_hash': TRAINING_PARAMETER_CATALOG_HASH,
        'training_parameter_contract_version': (
            TRAINING_PARAMETER_CONTRACT_VERSION
        ),
        'ranking_metric': FINETUNE_RANKING_METRIC,
        'allowed_image_sizes': list(FINETUNE_ALLOWED_IMAGE_SIZES),
        'cache_modes': list(FINETUNE_CACHE_MODES),
        'optimizer_modes': list(FINETUNE_OPTIMIZER_MODES),
        'explicit_optimizers': list(FINETUNE_EXPLICIT_OPTIMIZERS),
        'parameter_defaults': dict(FINETUNE_PARAMETER_DEFAULTS),
        'parameter_fields': list(FINETUNE_PARAMETER_FIELDS),
        'parameter_sets': list_finetune_parameter_sets(
            include_archived=include_archived
        ),
    }


def _finetune_replay_matches_payload(batch, tasks, payload):
    try:
        project_id = int(payload.get('project_id'))
        parent_model_id = int(payload.get('parent_model_id'))
        parameter_set_ids = [
            int(value)
            for value in (payload.get('parameter_set_ids') or [])
        ]
        requested_splits = payload.get('splits') or {
            'train': 80,
            'val': 20,
            'test': 0,
        }
        normalized_splits = {
            split: int(requested_splits.get(split, 0) or 0)
            for split in ('train', 'val', 'test')
        }
        max_attempts = int(payload.get('max_attempts') or 3)
        priority = int(payload.get('priority') or 0)
    except (TypeError, ValueError, AttributeError):
        return False
    ordered_tasks = sorted(tasks, key=lambda task: task.id)
    if (
        batch.experiment_type != 'finetune_sweep'
        or batch.parent_model_id != parent_model_id
        or len(ordered_tasks) != len(parameter_set_ids)
        or [task.project_id for task in ordered_tasks]
        != [project_id] * len(ordered_tasks)
        or [task.parameter_set_id for task in ordered_tasks]
        != parameter_set_ids
    ):
        return False
    requested_name = str(payload.get('name') or '').strip()
    if requested_name and batch.name != requested_name[:160]:
        return False
    expected_dataset_config = {
        'splits': normalized_splits,
        'include_unlabeled': bool(payload.get('include_unlabeled', False)),
        'exclude_flagged': bool(payload.get('exclude_flagged', True)),
    }
    return all(
        (task.dataset_config or {}) == expected_dataset_config
        and task.max_attempts == max_attempts
        and task.priority == priority
        for task in ordered_tasks
    )


def create_finetune_experiment(payload):
    submission_id = _normalize_finetune_submission_id(payload)
    if submission_id is None:
        batch, tasks = _create_finetune_experiment_once(payload)
        batch._idempotent_replay = False
        return batch, tasks

    with _finetune_submission_guard(submission_id):
        existing_batch = TrainingBatch.query.filter_by(
            batch_id=submission_id
        ).first()
        if existing_batch is not None:
            existing_tasks = TrainingQueueTask.query.filter_by(
                batch_id=existing_batch.id
            ).order_by(TrainingQueueTask.id.asc()).all()
            if not _finetune_replay_matches_payload(
                existing_batch,
                existing_tasks,
                payload,
            ):
                raise ValueError(
                    'idempotency_key was already used for a different '
                    'fine-tune request.'
                )
            existing_batch._idempotent_replay = True
            return existing_batch, existing_tasks

        batch, tasks = _create_finetune_experiment_once(
            payload,
            batch_id=submission_id,
        )
        batch._idempotent_replay = False
        return batch, tasks


def _create_finetune_experiment_once(payload, batch_id=None):
    if not current_app.config.get('TOOLIB_FINETUNE_ENABLED', False):
        raise ValueError('Fine-tune experiments are disabled.')

    try:
        project_id = int(payload.get('project_id'))
        parent_model_id = int(payload.get('parent_model_id'))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'project_id and parent_model_id must be integers.'
        ) from exc
    project = db.session.get(Project, project_id)
    if project is None:
        raise ValueError('project_id does not exist.')
    parent_model = db.session.get(AIModel, parent_model_id)
    if parent_model is None:
        raise ValueError('parent_model_id does not exist.')
    if (
        parent_model.model_type != 'detection'
        or parent_model.finetune_status != 'ready'
        or parent_artifact_for_model(parent_model) is None
    ):
        raise ValueError('Parent model is not ready for fine-tune.')

    ensure_default_finetune_parameter_sets()
    raw_parameter_set_ids = payload.get('parameter_set_ids')
    if (
        not isinstance(raw_parameter_set_ids, list)
        or not raw_parameter_set_ids
    ):
        raise ValueError(
            'parameter_set_ids must be a non-empty JSON array.'
        )
    if len(raw_parameter_set_ids) > 100:
        raise ValueError(
            'A fine-tune experiment can contain at most 100 parameter sets.'
        )
    parameter_set_ids = []
    seen_parameter_set_ids = set()
    for index, raw_parameter_set_id in enumerate(raw_parameter_set_ids):
        if isinstance(raw_parameter_set_id, bool):
            raise ValueError(
                f'parameter_set_ids[{index}] must be an integer.'
            )
        try:
            parameter_set_id = int(raw_parameter_set_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f'parameter_set_ids[{index}] must be an integer.'
            ) from exc
        if parameter_set_id in seen_parameter_set_ids:
            raise ValueError('parameter_set_ids must not contain duplicates.')
        seen_parameter_set_ids.add(parameter_set_id)
        parameter_set_ids.append(parameter_set_id)

    parameter_sets_by_id = {
        parameter_set.id: parameter_set
        for parameter_set in FineTuneParameterSet.query.filter(
            FineTuneParameterSet.id.in_(parameter_set_ids)
        ).all()
    }
    missing_parameter_set_ids = [
        parameter_set_id
        for parameter_set_id in parameter_set_ids
        if parameter_set_id not in parameter_sets_by_id
    ]
    if missing_parameter_set_ids:
        raise ValueError(
            'Unknown parameter_set_ids: '
            + ', '.join(str(value) for value in missing_parameter_set_ids)
        )
    parameter_sets = [
        parameter_sets_by_id[parameter_set_id]
        for parameter_set_id in parameter_set_ids
    ]
    inactive_parameter_sets = [
        parameter_set.name
        for parameter_set in parameter_sets
        if not parameter_set.is_active
    ]
    if inactive_parameter_sets:
        raise ValueError(
            'Archived parameter sets cannot start new experiments: '
            + ', '.join(inactive_parameter_sets)
        )
    invalid_tasks = [
        parameter_set.name
        for parameter_set in parameter_sets
        if parameter_set.model_task != 'detect'
    ]
    if invalid_tasks:
        raise ValueError(
            'Only detect parameter sets are supported: '
            + ', '.join(invalid_tasks)
        )

    splits = payload.get('splits') or {'train': 80, 'val': 20, 'test': 0}
    dataset = prepare_training_dataset_snapshot(
        project_id=project_id,
        splits=splits,
        include_unlabeled=bool(payload.get('include_unlabeled', False)),
        exclude_flagged=bool(payload.get('exclude_flagged', True)),
        storage_root=current_app.config.get(
            'TRAINING_DATASET_ROOT',
            os.path.join(os.path.dirname(__file__), 'training_datasets'),
        ),
        clear_header_callback=current_app.config.get(
            'TRAINING_CLEAR_HEADER_CALLBACK',
            default_clear_header_callback,
        ),
    )
    parent_classes = _canonical_class_names(parent_model.class_names)
    dataset_classes = _canonical_class_names(dataset.class_names)
    if not parent_classes:
        raise ValueError('Parent model has no validated class metadata.')
    if parent_classes != dataset_classes:
        raise ValueError(
            'Parent model classes must exactly match the dataset snapshot '
            f'(model={parent_classes}, dataset={dataset_classes}).'
        )

    jobs = []
    for candidate_index, parameter_set in enumerate(parameter_sets, start=1):
        parameters = normalize_finetune_parameter_set_parameters(
            parameter_set.parameters or {}
        )
        jobs.append({
            'project_id': project_id,
            'training_dataset_id': dataset.id,
            'training_mode': 'finetune',
            'parent_model_id': parent_model.id,
            'parameter_set_id': parameter_set.id,
            'candidate_name': (
                f'{candidate_index}. {parameter_set.name}'
            ),
            'model': parent_model.filename,
            **parameters,
            'priority': int(payload.get('priority') or 0),
            'max_attempts': int(payload.get('max_attempts') or 3),
            'splits': splits,
            'include_unlabeled': bool(
                payload.get('include_unlabeled', False)
            ),
            'exclude_flagged': bool(payload.get('exclude_flagged', True)),
        })

    name = str(payload.get('name') or '').strip()
    if not name:
        name = (
            f'Fine-tune {parent_model.name} on {project.name} '
            f'({len(parameter_sets)} parameter sets)'
        )
    return create_training_batch({
        'batch_id': batch_id,
        'name': name,
        'experiment_type': 'finetune_sweep',
        'parent_model_id': parent_model.id,
        'training_dataset_id': dataset.id,
        'preset_version': FINETUNE_PRESET_VERSION,
        'ranking_metric': FINETUNE_RANKING_METRIC,
        'max_attempts': int(payload.get('max_attempts') or 3),
        'jobs': jobs,
    })


def _lease_duration():
    seconds = int(current_app.config.get('TRAINING_TASK_LEASE_SECONDS', 300))
    return timedelta(seconds=max(seconds, 30))


def _retry_delay(attempt_count):
    base_seconds = int(current_app.config.get('TRAINING_RETRY_BASE_SECONDS', 15))
    maximum_seconds = int(current_app.config.get('TRAINING_RETRY_MAX_SECONDS', 900))
    return timedelta(
        seconds=min(base_seconds * (2 ** max(attempt_count - 1, 0)), maximum_seconds)
    )


def _worker_loss_grace():
    seconds = int(
        current_app.config.get('TRAINING_WORKER_LOSS_GRACE_SECONDS', 120)
    )
    return timedelta(seconds=max(seconds, 30))


def _latest_ready_checkpoint(task_id):
    return TrainingCheckpoint.query.filter_by(
        task_id=task_id,
        status='ready',
    ).order_by(
        TrainingCheckpoint.generation.desc(),
        TrainingCheckpoint.epoch.desc(),
        TrainingCheckpoint.id.desc(),
    ).first()


def _latest_resumable_checkpoint(task):
    total_epochs = int((task.request_payload or {}).get('epochs') or 1)
    return TrainingCheckpoint.query.filter(
        TrainingCheckpoint.task_id == task.id,
        TrainingCheckpoint.status == 'ready',
        TrainingCheckpoint.epoch < total_epochs,
    ).order_by(
        TrainingCheckpoint.generation.desc(),
        TrainingCheckpoint.epoch.desc(),
        TrainingCheckpoint.id.desc(),
    ).first()


def _checkpoint_object_key(store, task, generation, epoch):
    return store.object_key(
        'training',
        task.task_id,
        'checkpoints',
        f'generation-{int(generation):03d}',
        f'epoch-{int(epoch):04d}.pt',
    )


def _sync_training_checkpoint(task, worker, remote_payload):
    checkpoint_payload = remote_payload.get('latest_checkpoint')
    if not isinstance(checkpoint_payload, dict):
        return None
    store = checkpoint_store()
    if not store.enabled:
        return None

    try:
        checkpoint_id = str(
            uuid.UUID(str(checkpoint_payload.get('checkpoint_id') or ''))
        )
        generation = int(checkpoint_payload.get('generation'))
        epoch = int(checkpoint_payload.get('epoch'))
        total_epochs = int(checkpoint_payload.get('total_epochs'))
        size_bytes = int(checkpoint_payload.get('size_bytes'))
        sha256 = str(checkpoint_payload.get('sha256') or '').strip().lower()
    except (TypeError, ValueError, AttributeError):
        return None
    if (
        generation != task.recovery_generation
        or epoch < 1
        or total_epochs < epoch
        or size_bytes <= 0
        or len(sha256) != 64
    ):
        return None
    try:
        int(sha256, 16)
    except ValueError:
        return None

    expected_key = _checkpoint_object_key(
        store,
        task,
        generation,
        epoch,
    )
    object_key = str(checkpoint_payload.get('object_key') or '')
    if object_key != expected_key:
        return None
    try:
        stored_object = store.head(object_key)
    except ObjectStoreError:
        current_app.logger.warning(
            'Checkpoint metadata arrived before object verification',
            extra={
                'task_id': task.task_id,
                'checkpoint_id': checkpoint_id,
            },
        )
        return None
    if stored_object.size_bytes != size_bytes:
        return None

    checkpoint = TrainingCheckpoint.query.filter_by(
        task_id=task.id,
        generation=generation,
        epoch=epoch,
    ).first()
    if checkpoint is None:
        checkpoint = TrainingCheckpoint(
            checkpoint_id=checkpoint_id,
            task_id=task.id,
            generation=generation,
            epoch=epoch,
            total_epochs=total_epochs,
            status='ready',
            storage_backend=store.backend_name,
            object_key=object_key,
            sha256=sha256,
            size_bytes=size_bytes,
        )
        db.session.add(checkpoint)
    elif (
        checkpoint.checkpoint_id != checkpoint_id
        or checkpoint.sha256 != sha256
        or checkpoint.size_bytes != size_bytes
    ):
        raise WorkerApiError(
            'Worker reported conflicting checkpoint identity metadata.'
        )
    checkpoint.attempt_id = (
        TrainingJobAttempt.query.filter_by(
            task_id=task.id,
            attempt_number=task.attempt_count,
        ).with_entities(TrainingJobAttempt.id).scalar()
    )
    checkpoint.worker_id = worker.id
    checkpoint.status = 'ready'
    checkpoint.verified_at = utcnow()
    checkpoint.metadata_json = {
        'etag': stored_object.etag,
        'uploaded_at': checkpoint_payload.get('uploaded_at'),
    }
    db.session.flush()

    ready_checkpoints = TrainingCheckpoint.query.filter_by(
        task_id=task.id,
        status='ready',
    ).order_by(
        TrainingCheckpoint.generation.desc(),
        TrainingCheckpoint.epoch.desc(),
        TrainingCheckpoint.id.desc(),
    ).all()
    for stale_checkpoint in ready_checkpoints[2:]:
        stale_checkpoint.status = 'superseded'
        try:
            store.delete(stale_checkpoint.object_key)
        except ObjectStoreError:
            current_app.logger.warning(
                'Could not delete superseded checkpoint object',
                extra={
                    'task_id': task.task_id,
                    'checkpoint_id': stale_checkpoint.checkpoint_id,
                },
            )
    return checkpoint


def _build_checkpoint_uploads(task, attempt, worker, store):
    capabilities = worker.capabilities or {}
    if not store.enabled or not capabilities.get('checkpoint_upload'):
        return []
    total_epochs = int((task.request_payload or {}).get('epochs') or 1)
    start_epoch = int(attempt.resumed_from_epoch or 0)
    interval = max(int(task.checkpoint_interval or 5), 1)
    first_epoch = ((start_epoch // interval) + 1) * interval
    epochs = list(range(first_epoch, total_epochs + 1, interval))
    if total_epochs > start_epoch and total_epochs not in epochs:
        epochs.append(total_epochs)
    if len(epochs) > 64:
        raise WorkerApiError(
            'Checkpoint policy creates more than 64 upload targets.'
        )
    return [
        {
            'checkpoint_id': str(uuid.uuid4()),
            'epoch': epoch,
            'object_key': _checkpoint_object_key(
                store,
                task,
                attempt.generation,
                epoch,
            ),
        }
        for epoch in epochs
    ]


def _build_remote_training_request(task, attempt, worker, dataset):
    payload = dict(task.request_payload or {})
    payload['dataset_id'] = dataset.dataset_id
    capabilities = worker.capabilities or {}
    store = checkpoint_store()
    if store.enabled and _worker_supports_object_inputs(worker):
        if not dataset.object_key:
            raise WorkerApiError(
                'Dataset object metadata is missing before submission.'
            )
        payload['dataset_object'] = _object_download_payload(
            store,
            object_key=dataset.object_key,
            sha256=dataset.archive_sha256,
            size_bytes=dataset.archive_size,
        )
        training_mode = str(payload.get('training_mode') or 'fresh')
        if training_mode == 'finetune' and attempt.attempt_kind != 'resume':
            parent_model = db.session.get(AIModel, task.parent_model_id)
            parent_artifact = (
                parent_artifact_for_model(parent_model)
                if parent_model is not None else None
            )
            if parent_artifact is None or not parent_artifact.object_key:
                raise WorkerApiError(
                    'Parent object metadata is missing before submission.'
                )
            payload['parent_object'] = {
                'artifact_id': parent_artifact.artifact_id,
                **_object_download_payload(
                    store,
                    object_key=parent_artifact.object_key,
                    sha256=parent_artifact.sha256,
                    size_bytes=parent_artifact.size_bytes,
                ),
            }
    if store.enabled and _worker_supports_object_artifacts(worker):
        payload['artifact_uploads'] = _artifact_upload_targets(
            store,
            task,
            attempt,
        )
    supports_checkpoint_protocol = bool(
        capabilities.get('checkpoint_upload')
        and capabilities.get('checkpoint_resume')
    )
    if not supports_checkpoint_protocol or not store.enabled:
        if attempt.attempt_kind == 'resume':
            raise WorkerApiError(
                'Resume attempt requires checkpoint-capable worker and object storage.'
            )
        return payload

    upload_targets = _build_checkpoint_uploads(
        task,
        attempt,
        worker,
        store,
    )
    for target in upload_targets:
        target['upload_url'] = store.presign_upload(target['object_key'])
    payload.update({
        'execution_mode': attempt.attempt_kind,
        'recovery_generation': attempt.generation,
        'checkpoint_interval': task.checkpoint_interval,
        'checkpoint_uploads': upload_targets,
    })
    if attempt.attempt_kind == 'resume':
        checkpoint = db.session.get(
            TrainingCheckpoint,
            attempt.resume_checkpoint_id,
        )
        if checkpoint is None or checkpoint.status != 'ready':
            raise WorkerApiError('Resume checkpoint is no longer available.')
        stored_object = store.head(checkpoint.object_key)
        if stored_object.size_bytes != checkpoint.size_bytes:
            raise WorkerApiError('Resume checkpoint size verification failed.')
        payload['resume_checkpoint'] = {
            'checkpoint_id': checkpoint.checkpoint_id,
            'epoch': checkpoint.epoch,
            'total_epochs': checkpoint.total_epochs,
            'object_key': checkpoint.object_key,
            'sha256': checkpoint.sha256,
            'size_bytes': checkpoint.size_bytes,
            'download_url': store.presign_download(checkpoint.object_key),
        }
    return payload


def _attempt_is_current(task, attempt):
    return bool(
        task.lease_token
        and task.lease_token == attempt.lease_token
        and task.assigned_worker_id == attempt.worker_id
        and task.recovery_generation == attempt.generation
    )


def _claim_task_for_worker(task, worker):
    if task.status not in DISPATCHABLE_TASK_STATUSES:
        return None
    if task.next_attempt_at and task.next_attempt_at > utcnow():
        return None
    if _active_lease_count(worker.id) >= worker.capacity:
        return None

    is_resume = task.status == 'resume_pending'
    resume_checkpoint = (
        _latest_resumable_checkpoint(task) if is_resume else None
    )
    if is_resume and resume_checkpoint is None:
        return None
    lease_token = str(uuid.uuid4())
    task.attempt_count += 1
    task.assigned_worker_id = worker.id
    task.lease_token = lease_token
    task.lease_expires_at = utcnow() + _lease_duration()
    task.next_attempt_at = None
    task.error = None
    task.effective_config = None
    transition_task(
        task,
        'preparing_dataset',
        'preparing_dataset',
        f'Attempt {task.attempt_count} assigned to {worker.name}.',
        details={'worker_id': worker.worker_id},
    )
    attempt = TrainingJobAttempt(
        attempt_id=str(uuid.uuid4()),
        task_id=task.id,
        worker_id=worker.id,
        attempt_number=task.attempt_count,
        attempt_kind='resume' if is_resume else 'initial',
        generation=task.recovery_generation,
        resume_checkpoint_id=(
            resume_checkpoint.id if resume_checkpoint else None
        ),
        resumed_from_epoch=(
            resume_checkpoint.epoch if resume_checkpoint else None
        ),
        status='leased',
        lease_token=lease_token,
        heartbeat_at=utcnow(),
    )
    db.session.add(attempt)
    db.session.flush()
    record_task_event(
        task,
        'lease_acquired',
        message=f'Lease acquired by worker {worker.name}.',
        details={'worker_id': worker.worker_id, 'lease_token': lease_token},
        attempt=attempt,
    )
    db.session.commit()
    return attempt


def _sync_local_training_job(task, worker, remote_payload):
    remote_job_id = normalize_remote_job_id(remote_payload.get('job_id'))

    job = TrainingJob.query.filter_by(remote_job_id=remote_job_id).first()
    if job is None:
        job = TrainingJob(
            remote_job_id=remote_job_id,
            remote_api_url=worker.api_url,
            status=str(remote_payload.get('status') or 'queued')[:20],
        )
        db.session.add(job)

    dataset = (
        db.session.get(TrainingDataset, task.training_dataset_id)
        if task.training_dataset_id
        else None
    )
    job.project_id = task.project_id
    job.training_dataset_id = dataset.id if dataset else None
    job.dataset_id = dataset.dataset_id if dataset else None
    job.remote_api_url = worker.api_url
    job.status = str(remote_payload.get('status') or job.status or 'queued')[:20]
    request_payload = dict(task.request_payload or {})
    if dataset is not None:
        request_payload['dataset_id'] = dataset.dataset_id
    job.request_payload = request_payload
    job.training_mode = str(
        request_payload.get('training_mode') or 'fresh'
    )[:30]
    job.parent_model_id = task.parent_model_id
    job.model = str(remote_payload.get('model') or request_payload.get('model') or '')[:100] or None
    job.epochs = int(remote_payload.get('epochs') or request_payload.get('epochs') or 1)
    job.batch = int(remote_payload.get('batch') or request_payload.get('batch') or 1)
    job.imgsz = int(remote_payload.get('imgsz') or request_payload.get('imgsz') or 640)
    job.current_epoch = int(remote_payload.get('current_epoch') or 0)
    job.total_epochs = int(remote_payload.get('total_epochs') or job.epochs or 0)
    job.message = str(remote_payload.get('message') or '')[:4000] or None
    job.error = str(remote_payload.get('error') or '')[:8000] or None
    artifacts = remote_payload.get('artifacts')
    if isinstance(artifacts, dict):
        job.artifacts = artifacts
    metrics = remote_payload.get('metrics')
    if isinstance(metrics, dict):
        job.metrics = metrics
        task.metrics = metrics
    effective_config = remote_payload.get('effective_config')
    if isinstance(effective_config, dict):
        job.effective_config = effective_config
        task.effective_config = effective_config
    job.connection_status = 'synced'
    job.last_sync_error = None
    job.last_synced_at = utcnow()
    db.session.flush()

    linked_task = TrainingQueueTask.query.filter(
        TrainingQueueTask.training_job_id == job.id,
        TrainingQueueTask.id != task.id,
    ).first()
    if linked_task is not None:
        raise WorkerApiError(
            f'Remote job {remote_job_id} is already linked to '
            f'task {linked_task.task_id}.'
        )
    task.training_job_id = job.id
    current_attempt = TrainingJobAttempt.query.filter_by(
        task_id=task.id,
        attempt_number=task.attempt_count,
    ).first()
    if current_attempt is not None:
        current_attempt.training_job_id = job.id
    _sync_training_checkpoint(task, worker, remote_payload)
    if job.status in REMOTE_TERMINAL_STATUSES:
        if worker.remote_active_job_id == remote_job_id:
            worker.remote_active_job_id = None
    else:
        worker.remote_active_job_id = remote_job_id
    return job


def _persist_remote_acceptance(task, attempt, worker, remote_payload):
    remote_job_id = normalize_remote_job_id(remote_payload.get('job_id'))
    existing_attempt = TrainingJobAttempt.query.filter(
        TrainingJobAttempt.remote_job_id == remote_job_id,
        TrainingJobAttempt.task_id != task.id,
    ).first()
    if existing_attempt is not None:
        raise WorkerApiError(
            f'Remote job {remote_job_id} is already owned by another task.'
        )

    attempt.remote_job_id = remote_job_id
    attempt.status = 'running'
    attempt.heartbeat_at = utcnow()
    worker.remote_active_job_id = remote_job_id
    record_task_event(
        task,
        'remote_submission_accepted',
        message=f'Remote worker accepted job {remote_job_id}.',
        details={
            'remote_job_id': remote_job_id,
            'worker_id': worker.worker_id,
        },
        attempt=attempt,
    )
    # This commit is intentionally separate from TrainingJob synchronization.
    # Once the remote API accepts a job, its identity must survive any later
    # local model/constraint error so reconciliation can resume without retrying.
    db.session.commit()
    return remote_job_id


def _submission_idempotency_key(task):
    remote_job_ids = {
        remote_job_id
        for (remote_job_id,) in db.session.query(
            TrainingJobAttempt.remote_job_id
        ).filter(
            TrainingJobAttempt.task_id == task.id,
            TrainingJobAttempt.remote_job_id.isnot(None),
        ).all()
    }
    failed_remote_jobs = 0
    if remote_job_ids:
        failed_remote_jobs = TrainingJob.query.filter(
            TrainingJob.remote_job_id.in_(remote_job_ids),
            TrainingJob.status == 'failed',
        ).count()
    generation = max(
        failed_remote_jobs + 1,
        int(task.recovery_generation or 1),
    )
    key_digest = hashlib.sha256(
        task.idempotency_key.encode('utf-8')
    ).hexdigest()[:16]
    return f'toolib:{task.task_id}:run:{generation}:{key_digest}'


def _read_training_metrics(results_path):
    if results_path is None or not Path(results_path).is_file():
        return {}
    try:
        with Path(results_path).open(
            'r',
            encoding='utf-8-sig',
            newline='',
        ) as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, csv.Error):
        return {}
    if not rows:
        return {}

    metrics = {}
    for raw_key, raw_value in rows[-1].items():
        key = str(raw_key or '').strip()
        value = str(raw_value or '').strip()
        if not key or not value:
            continue
        try:
            metrics[key] = float(value)
        except ValueError:
            metrics[key] = value
    return metrics


def _build_imported_model_name(task, job, parent_model=None):
    if parent_model is not None and str(parent_model.name or '').strip():
        base_name = str(parent_model.name).strip()
    else:
        model_name = Path(str(job.model or 'YOLO')).name
        base_name = (
            model_name[:-3]
            if model_name.lower().endswith('.pt')
            else model_name
        ).strip() or 'YOLO'

    parameter_snapshot = task.parameter_set_snapshot
    preset_name = ''
    if isinstance(parameter_snapshot, dict):
        preset_name = str(parameter_snapshot.get('name') or '').strip()

    task_suffix = str(task.task_id or '')[:8] or 'training'
    separator = ' · '
    max_length = 100

    if not preset_name:
        legacy_prefix = f'Automated {job.model or "YOLO"} -'
        prefix_budget = max_length - 1 - len(task_suffix)
        return (
            f'{_truncate_display_segment(legacy_prefix, prefix_budget)}'
            f' {task_suffix}'
        )

    content_budget = max_length - (2 * len(separator)) - len(task_suffix)
    base_budget = min(len(base_name), max(20, content_budget // 2))
    preset_budget = content_budget - base_budget
    if len(preset_name) < preset_budget:
        base_budget += preset_budget - len(preset_name)
    elif len(base_name) < base_budget:
        preset_budget += base_budget - len(base_name)

    return separator.join((
        _truncate_display_segment(base_name, base_budget),
        _truncate_display_segment(preset_name, preset_budget),
        task_suffix,
    ))


def _truncate_display_segment(value, max_length):
    value = str(value or '').strip()
    if len(value) <= max_length:
        return value
    if max_length <= 1:
        return value[:max_length]
    return f'{value[:max_length - 1].rstrip()}…'


def _import_task_model(task, job, artifact_paths, artifact_objects=None):
    artifact_objects = artifact_objects or {}
    if task.imported_model_id is not None:
        model = db.session.get(AIModel, task.imported_model_id)
        if model is not None:
            return model

    onnx_path = Path(artifact_paths['onnx']).resolve()
    models_root = Path(
        current_app.config.get(
            'MODEL_STORAGE_ROOT',
            os.path.join(os.path.dirname(__file__), 'models'),
        )
    ).resolve()
    models_root.mkdir(parents=True, exist_ok=True)
    filename = f'training_{task.task_id[:8]}_{job.remote_job_id[:8]}.onnx'
    destination = (models_root / filename).resolve()
    try:
        destination.relative_to(models_root)
    except ValueError as exc:
        raise ValueError('Invalid model storage path.') from exc

    existing = AIModel.query.filter_by(filename=filename).first()
    if existing is None:
        parent_model = (
            db.session.get(AIModel, task.parent_model_id)
            if task.parent_model_id
            else None
        )
        temporary_path = destination.with_suffix('.onnx.part')
        shutil.copy2(onnx_path, temporary_path)
        temporary_path.replace(destination)
        existing = AIModel(
            name=_build_imported_model_name(task, job, parent_model),
            description=(
                f'{job.training_mode} task {task.task_id}; '
                f'remote job {job.remote_job_id}; '
                f'epochs={job.epochs}; batch={job.batch}; imgsz={job.imgsz}'
            ),
            filename=filename,
            model_type='detection',
            is_active=False,
            activation_ready=False,
            parent_model_id=task.parent_model_id,
            source_project_id=task.project_id,
            training_dataset_id=task.training_dataset_id,
            source_kind='training',
            finetune_status=(
                'ready' if artifact_paths.get('pt') else 'unavailable'
            ),
        )
        if parent_model is not None:
            existing.class_names = parent_model.class_names
        elif task.training_dataset_id:
            dataset = db.session.get(
                TrainingDataset,
                task.training_dataset_id,
            )
            if dataset is not None:
                existing.class_names = dataset.class_names
        db.session.add(existing)
        db.session.flush()

    artifact_kind_mapping = {
        'onnx': 'onnx',
        'pt': 'best_pt',
        'last_pt': 'last_pt',
        'manifest': 'manifest',
        'results': 'results',
        'args': 'args',
    }
    for remote_kind, model_kind in artifact_kind_mapping.items():
        local_path = artifact_paths.get(remote_kind)
        if local_path is None:
            continue
        local_path = Path(local_path).resolve()
        if not local_path.is_file():
            continue
        artifact = ModelArtifact.query.filter_by(
            model_id=existing.id,
            kind=model_kind,
        ).first()
        if artifact is None:
            object_metadata = artifact_objects.get(remote_kind) or {}
            artifact = ModelArtifact(
                artifact_id=str(uuid.uuid4()),
                model_id=existing.id,
                kind=model_kind,
                storage_path=str(local_path),
                storage_backend=(
                    's3' if object_metadata.get('object_key') else 'local'
                ),
                object_key=object_metadata.get('object_key'),
                object_verified_at=(
                    utcnow() if object_metadata.get('object_key') else None
                ),
                sha256=sha256_path(local_path),
                size_bytes=local_path.stat().st_size,
                metadata_json={
                    'task_id': task.task_id,
                    'remote_job_id': job.remote_job_id,
                    'object_transport': bool(
                        object_metadata.get('object_key')
                    ),
                },
            )
            db.session.add(artifact)
        elif artifact_objects.get(remote_kind):
            object_metadata = artifact_objects[remote_kind]
            artifact.storage_backend = 's3'
            artifact.object_key = object_metadata.get('object_key')
            artifact.object_verified_at = utcnow()

    metrics = dict(job.metrics or {})
    if not metrics:
        metrics = _read_training_metrics(artifact_paths.get('results'))
    task.metrics = metrics or None
    job.metrics = metrics or None
    task.imported_model_id = existing.id
    job.imported_model_id = existing.id
    return existing


def _renew_lease(task, attempt):
    task.lease_expires_at = utcnow() + _lease_duration()
    attempt.heartbeat_at = utcnow()


class _TaskLeaseHeartbeat:
    def __init__(self, app, task, attempt):
        self.app = app
        self.task_id = task.id
        self.attempt_id = attempt.id
        self.lease_token = task.lease_token
        configured_interval = app.config.get(
            'TRAINING_TASK_HEARTBEAT_SECONDS'
        )
        if configured_interval is None:
            lease_seconds = max(
                int(app.config.get('TRAINING_TASK_LEASE_SECONDS', 300)),
                30,
            )
            configured_interval = min(lease_seconds / 3, 30)
        self.interval_seconds = max(float(configured_interval), 0.05)
        self.stop_event = threading.Event()
        self.thread = None

    def __enter__(self):
        self.thread = threading.Thread(
            target=self._run,
            name=f'training-lease-heartbeat-{self.task_id}',
            daemon=True,
        )
        self.thread.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=max(self.interval_seconds * 2, 1))

    def _run(self):
        while not self.stop_event.wait(self.interval_seconds):
            with self.app.app_context():
                try:
                    task = db.session.get(TrainingQueueTask, self.task_id)
                    attempt = db.session.get(
                        TrainingJobAttempt,
                        self.attempt_id,
                    )
                    if (
                        task is None
                        or attempt is None
                        or task.lease_token != self.lease_token
                        or task.status not in ACTIVE_TASK_STATUSES
                    ):
                        return
                    _renew_lease(task, attempt)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    current_app.logger.exception(
                        'Could not renew training artifact download lease',
                        extra={
                            'task_id': self.task_id,
                            'attempt_id': self.attempt_id,
                        },
                    )
                finally:
                    db.session.remove()


def _handle_pipeline_failure(task, attempt, exc):
    error_message = str(exc)[:8000]
    task.error = error_message
    attempt.error = error_message
    attempt.finished_at = utcnow()
    task.lease_token = None
    task.lease_expires_at = None

    if isinstance(exc, WorkerBusyError):
        attempt.status = 'blocked'
        task.assigned_worker_id = None
        task.next_attempt_at = utcnow() + _retry_delay(task.attempt_count)
        if task.attempt_count >= task.max_attempts:
            task.max_attempts = task.attempt_count + 1
        worker = (
            db.session.get(TrainingWorker, attempt.worker_id)
            if attempt.worker_id
            else None
        )
        if worker is not None:
            worker.remote_active_job_id = exc.active_job_id
        transition_task(
            task,
            'waiting_for_worker',
            'waiting_for_worker',
            'Worker is busy; task returned to the queue without consuming '
            'a training failure.',
            attempt=attempt,
            details={
                'active_job_id': exc.active_job_id,
                'error_type': type(exc).__name__,
            },
        )
    elif (
        attempt.remote_job_id
        and not isinstance(exc, RemoteTrainingFailedError)
    ):
        lost_at = utcnow()
        attempt.status = 'worker_lost'
        task.worker_lost_at = task.worker_lost_at or lost_at
        task.recovery_deadline_at = (
            task.recovery_deadline_at
            or lost_at + _worker_loss_grace()
        )
        transition_task(
            task,
            'worker_lost',
            'waiting_for_worker_reconnect',
            'Remote job was accepted but local processing was interrupted; '
            'reconciliation will resume the same job.',
            attempt=attempt,
            details={'remote_job_id': attempt.remote_job_id},
        )
    elif task.attempt_count < task.max_attempts:
        attempt.status = 'failed'
        task.assigned_worker_id = None
        task.worker_lost_at = None
        task.recovery_deadline_at = None
        task.next_attempt_at = utcnow() + _retry_delay(task.attempt_count)
        transition_task(
            task,
            'retry_wait',
            'retry_wait',
            f'Attempt failed; retry {task.attempt_count + 1}/{task.max_attempts} scheduled.',
            attempt=attempt,
            details={'error_type': type(exc).__name__},
        )
    else:
        attempt.status = 'failed'
        task.worker_lost_at = None
        task.recovery_deadline_at = None
        transition_task(
            task,
            'failed',
            'failed',
            'Training task exhausted all attempts.',
            attempt=attempt,
            details={'error_type': type(exc).__name__},
        )
    refresh_batch_status(task.batch_id)
    db.session.commit()


def _process_task(app, task_id, attempt_id, adapter_factory):
    try:
        with app.app_context():
            task = db.session.get(TrainingQueueTask, task_id)
            attempt = db.session.get(TrainingJobAttempt, attempt_id)
            if task is None or attempt is None:
                return
            worker = db.session.get(TrainingWorker, attempt.worker_id)
            if worker is None or not worker.enabled:
                raise WorkerUnavailableError('Assigned worker is unavailable.')
            if not _attempt_is_current(task, attempt):
                return
            adapter = adapter_factory(worker)

            dataset = (
                db.session.get(TrainingDataset, task.training_dataset_id)
                if task.training_dataset_id
                else None
            )
            if dataset is None:
                dataset_config = task.dataset_config or {}
                dataset = prepare_training_dataset_snapshot(
                    project_id=task.project_id,
                    splits=dataset_config.get('splits') or {
                        'train': 80,
                        'val': 20,
                        'test': 0,
                    },
                    include_unlabeled=bool(
                        dataset_config.get('include_unlabeled', False)
                    ),
                    exclude_flagged=bool(
                        dataset_config.get('exclude_flagged', True)
                    ),
                    storage_root=current_app.config.get(
                        'TRAINING_DATASET_ROOT',
                        os.path.join(os.path.dirname(__file__), 'training_datasets'),
                    ),
                    clear_header_callback=current_app.config.get(
                        'TRAINING_CLEAR_HEADER_CALLBACK',
                        default_clear_header_callback,
                    ),
                )
                task.training_dataset_id = dataset.id
                db.session.commit()

            job = (
                db.session.get(TrainingJob, task.training_job_id)
                if task.training_job_id
                else None
            )
            if attempt.remote_job_id and (
                job is None
                or job.remote_job_id != attempt.remote_job_id
            ):
                remote_snapshot = adapter.get_job(attempt.remote_job_id)
                job = _sync_local_training_job(
                    task,
                    worker,
                    remote_snapshot,
                )
                db.session.commit()
            is_resuming_remote_job = (
                job is not None
                and attempt.remote_job_id
                and job.remote_job_id == attempt.remote_job_id
            )
            if is_resuming_remote_job:
                transition_task(
                    task,
                    'remote_running',
                    'remote_running',
                    f'Resuming remote job {job.remote_job_id}.',
                    attempt=attempt,
                )
                db.session.commit()
            else:
                training_mode = str(
                    (task.request_payload or {}).get('training_mode')
                    or 'fresh'
                )
                store = checkpoint_store()
                use_object_inputs = (
                    store.enabled
                    and _worker_supports_object_inputs(worker)
                )
                if (
                    training_mode == 'finetune'
                    and attempt.attempt_kind != 'resume'
                ):
                    parent_model = db.session.get(
                        AIModel,
                        task.parent_model_id,
                    )
                    if parent_model is None:
                        raise WorkerApiError(
                            'Fine-tune parent model no longer exists.'
                        )
                    parent_artifact = parent_artifact_for_model(parent_model)
                    if parent_artifact is None:
                        raise WorkerApiError(
                            'Fine-tune parent .pt artifact no longer exists.'
                        )
                    transition_task(
                        task,
                        'uploading_parent_model',
                        'uploading_parent_model',
                        (
                            f'Publishing parent model '
                            f'{parent_artifact.sha256[:12]} for {worker.name}.'
                            if use_object_inputs else
                            f'Caching parent model '
                            f'{parent_artifact.sha256[:12]} on {worker.name}.'
                        ),
                        attempt=attempt,
                    )
                    _renew_lease(task, attempt)
                    db.session.commit()
                    if use_object_inputs:
                        _ensure_parent_object(parent_artifact, store)
                        db.session.commit()
                    else:
                        remote_parent = adapter.upload_model_artifact(
                            parent_artifact
                        )
                        remote_classes = _canonical_class_names(
                            remote_parent.get('class_names')
                        )
                        if (
                            remote_classes
                            and remote_classes
                            != _canonical_class_names(parent_model.class_names)
                        ):
                            raise WorkerApiError(
                                'Worker checkpoint class metadata changed.'
                            )

                transition_task(
                    task,
                    'uploading_dataset',
                    'uploading_dataset',
                    (
                        f'Publishing dataset {dataset.dataset_id} to object storage.'
                        if use_object_inputs else
                        f'Uploading dataset {dataset.dataset_id} to {worker.name}.'
                    ),
                    attempt=attempt,
                )
                _renew_lease(task, attempt)
                db.session.commit()
                if use_object_inputs:
                    def mark_waiting_for_shared_dataset():
                        transition_task(
                            task,
                            'uploading_dataset',
                            'waiting_shared_dataset',
                            (
                                f'Waiting for shared dataset '
                                f'{dataset.dataset_id} to finish publishing.'
                            ),
                            attempt=attempt,
                        )
                        _renew_lease(task, attempt)
                        db.session.commit()

                    def heartbeat_shared_dataset_wait():
                        _renew_lease(task, attempt)
                        db.session.commit()

                    _object_key, reused_dataset = _ensure_dataset_object(
                        dataset,
                        store,
                        on_wait=mark_waiting_for_shared_dataset,
                        on_heartbeat=heartbeat_shared_dataset_wait,
                    )
                    transition_task(
                        task,
                        'uploading_dataset',
                        (
                            'reusing_shared_dataset'
                            if reused_dataset else
                            'published_shared_dataset'
                        ),
                        (
                            f'Reusing shared dataset object '
                            f'{dataset.archive_sha256[:12]}.'
                            if reused_dataset else
                            f'Published shared dataset object '
                            f'{dataset.archive_sha256[:12]}.'
                        ),
                        attempt=attempt,
                    )
                    _renew_lease(task, attempt)
                    remote_dataset = {
                        'object_key': dataset.object_key,
                        'storage_backend': dataset.storage_backend,
                    }
                else:
                    remote_dataset = adapter.upload_dataset(dataset)
                dataset.status = 'uploaded'
                dataset.remote_api_url = (
                    None if use_object_inputs else worker.api_url
                )
                dataset.remote_drive_path = (
                    str(remote_dataset.get('drive_path') or '')[:1000] or None
                )
                dataset.uploaded_at = utcnow()
                dataset.error = None
                db.session.commit()

                transition_task(
                    task,
                    'submitting',
                    'submitting',
                    'Submitting idempotent remote training request.',
                    attempt=attempt,
                )
                _renew_lease(task, attempt)
                db.session.commit()
                submit_payload = _build_remote_training_request(
                    task,
                    attempt,
                    worker,
                    dataset,
                )
                submission_key = _submission_idempotency_key(task)
                remote = adapter.submit_job(submit_payload, submission_key)
                _persist_remote_acceptance(task, attempt, worker, remote)
                job = _sync_local_training_job(task, worker, remote)
                transition_task(
                    task,
                    'remote_queued',
                    'remote_queued',
                    f'Remote job {job.remote_job_id} accepted.',
                    attempt=attempt,
                )
                db.session.commit()

            poll_seconds = max(
                float(current_app.config.get('TRAINING_REMOTE_POLL_SECONDS', 10)),
                0,
            )
            maximum_runtime = max(
                int(current_app.config.get('TRAINING_REMOTE_MAX_SECONDS', 12 * 3600)),
                60,
            )
            polling_started = time.monotonic()
            while True:
                if not _attempt_is_current(task, attempt):
                    raise WorkerUnavailableError(
                        'Attempt was superseded by a newer recovery generation.'
                    )
                if time.monotonic() - polling_started > maximum_runtime:
                    raise WorkerUnavailableError(
                        'Remote training exceeded the configured polling lifetime.'
                    )
                remote = adapter.get_job(job.remote_job_id)
                job = _sync_local_training_job(task, worker, remote)
                remote_status = job.status
                _renew_lease(task, attempt)
                attempt.heartbeat_at = utcnow()
                if remote_status == 'running':
                    transition_task(
                        task,
                        'remote_running',
                        'remote_running',
                        job.message or 'Remote training is running.',
                        attempt=attempt,
                        details={
                            'current_epoch': job.current_epoch,
                            'total_epochs': job.total_epochs,
                        },
                    )
                elif remote_status == 'queued':
                    transition_task(
                        task,
                        'remote_queued',
                        'remote_queued',
                        job.message or 'Remote job is queued.',
                        attempt=attempt,
                    )
                db.session.commit()
                if remote_status in REMOTE_TERMINAL_STATUSES:
                    break
                if poll_seconds:
                    time.sleep(poll_seconds)

            if job.status != 'succeeded':
                raise RemoteTrainingFailedError(
                    job.error or job.message or 'Remote training failed.'
                )
            if not _attempt_is_current(task, attempt):
                raise WorkerUnavailableError(
                    'Stale worker result was fenced before artifact import.'
                )

            transition_task(
                task,
                'downloading_artifacts',
                'downloading_artifacts',
                'Downloading training artifacts into the central artifact store.',
                attempt=attempt,
            )
            _renew_lease(task, attempt)
            db.session.commit()
            remote_artifacts = (
                job.artifacts if isinstance(job.artifacts, dict) else {}
            )
            artifact_objects = (
                remote_artifacts.get('_objects')
                if isinstance(remote_artifacts.get('_objects'), dict)
                else {}
            )
            mandatory_artifacts = {'onnx'}
            if job.training_mode == 'finetune':
                mandatory_artifacts.add('pt')
            artifact_paths = {}
            for artifact_kind in (
                'onnx',
                'pt',
                'last_pt',
                'manifest',
                'results',
                'args',
            ):
                if (
                    artifact_kind not in mandatory_artifacts
                    and artifact_kind not in remote_artifacts
                ):
                    continue
                destination = artifact_store().artifact_path(
                    task.task_id,
                    artifact_kind,
                )
                progress_state = {
                    'bytes': -1,
                    'reported_at': 0.0,
                }

                def report_artifact_progress(
                    downloaded_bytes,
                    total_bytes,
                    *,
                    current_kind=artifact_kind,
                ):
                    now = time.monotonic()
                    completed = (
                        total_bytes > 0
                        and downloaded_bytes >= total_bytes
                    )
                    should_report = (
                        downloaded_bytes == 0
                        or completed
                        or downloaded_bytes - progress_state['bytes']
                        >= 8 * 1024 * 1024
                        or now - progress_state['reported_at'] >= 5
                    )
                    if not should_report:
                        return
                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                    if total_bytes > 0:
                        total_mb = total_bytes / (1024 * 1024)
                        progress_text = (
                            f'{downloaded_mb:.1f}/{total_mb:.1f} MB'
                        )
                    else:
                        progress_text = f'{downloaded_mb:.1f} MB'
                    task.message = (
                        f'Downloading {current_kind.upper()} artifact: '
                        f'{progress_text}.'
                    )
                    _renew_lease(task, attempt)
                    db.session.commit()
                    progress_state['bytes'] = downloaded_bytes
                    progress_state['reported_at'] = now

                with _TaskLeaseHeartbeat(app, task, attempt):
                    object_metadata = artifact_objects.get(artifact_kind)
                    if object_metadata:
                        store = checkpoint_store()
                        if not store.enabled:
                            raise WorkerApiError(
                                'Worker returned object artifacts while storage is disabled.'
                            )
                        expected_key = _artifact_object_key(
                            store,
                            task,
                            attempt,
                            artifact_kind,
                        )
                        if object_metadata.get('object_key') != expected_key:
                            raise WorkerApiError(
                                f'{artifact_kind} artifact object key is not task-scoped.'
                            )
                        stored_object = store.head(expected_key)
                        expected_size = int(
                            object_metadata.get('size_bytes') or 0
                        )
                        if (
                            expected_size <= 0
                            or stored_object.size_bytes != expected_size
                        ):
                            raise WorkerApiError(
                                f'{artifact_kind} artifact size verification failed.'
                            )
                        task.message = (
                            f'Downloading {artifact_kind.upper()} directly '
                            'from object storage.'
                        )
                        db.session.commit()
                        store.download_file(expected_key, destination)
                        if (
                            sha256_path(destination)
                            != object_metadata.get('sha256')
                        ):
                            destination.unlink(missing_ok=True)
                            raise WorkerApiError(
                                f'{artifact_kind} artifact checksum verification failed.'
                            )
                    else:
                        adapter.download_artifact(
                            job.remote_job_id,
                            artifact_kind,
                            destination,
                            progress_callback=report_artifact_progress,
                        )
                if not destination.is_file() or destination.stat().st_size <= 0:
                    raise WorkerApiError(
                        f'Downloaded {artifact_kind} artifact is empty.'
                    )
                artifact_paths[artifact_kind] = destination

            transition_task(
                task,
                'importing_model',
                'importing_model',
                'Importing candidate model as inactive.',
                attempt=attempt,
            )
            db.session.commit()
            model = _import_task_model(
                task,
                job,
                artifact_paths,
                artifact_objects=artifact_objects,
            )
            attempt.status = 'succeeded'
            attempt.finished_at = utcnow()
            task.error = None
            task.worker_lost_at = None
            task.recovery_deadline_at = None
            transition_task(
                task,
                'succeeded',
                'succeeded',
                f'Imported inactive model #{model.id}.',
                attempt=attempt,
                details={
                    'model_id': model.id,
                    'remote_job_id': job.remote_job_id,
                    'artifact_sha256': {
                        kind: sha256_path(path)
                        for kind, path in artifact_paths.items()
                    },
                    'metrics': task.metrics or {},
                },
            )
            refresh_batch_status(task.batch_id)
            db.session.commit()
    except Exception as exc:
        with app.app_context():
            db.session.remove()
            task = db.session.get(TrainingQueueTask, task_id)
            attempt = db.session.get(TrainingJobAttempt, attempt_id)
            if task is not None and attempt is not None:
                if not _attempt_is_current(task, attempt):
                    attempt.status = 'superseded'
                    attempt.finished_at = attempt.finished_at or utcnow()
                    attempt.error = (
                        'Attempt result ignored after recovery generation changed.'
                    )
                    db.session.commit()
                    return
                current_app.logger.exception(
                    'Training task pipeline failed',
                    extra={
                        'task_id': task.task_id,
                        'attempt_id': attempt.attempt_id,
                    },
                )
                _handle_pipeline_failure(task, attempt, exc)
    finally:
        with _running_task_lock:
            _running_task_ids.discard(task_id)


def _submit_task_pipeline(app, task, attempt, adapter_factory, asynchronous):
    with _running_task_lock:
        if task.id in _running_task_ids:
            return False
        _running_task_ids.add(task.id)

    if asynchronous:
        _executor.submit(
            _process_task,
            app,
            task.id,
            attempt.id,
            adapter_factory,
        )
    else:
        _process_task(app, task.id, attempt.id, adapter_factory)
    return True


def recover_expired_leases():
    now = utcnow()
    expired = TrainingQueueTask.query.filter(
        TrainingQueueTask.status.in_(ACTIVE_TASK_STATUSES),
        TrainingQueueTask.lease_expires_at.isnot(None),
        TrainingQueueTask.lease_expires_at <= now,
    ).all()
    for task in expired:
        attempt = TrainingJobAttempt.query.filter_by(
            task_id=task.id,
            lease_token=task.lease_token,
        ).first()
        if attempt is None:
            continue
        if attempt.remote_job_id:
            attempt.status = 'worker_lost'
            task.worker_lost_at = task.worker_lost_at or now
            task.recovery_deadline_at = (
                task.recovery_deadline_at
                or now + _worker_loss_grace()
            )
            transition_task(
                task,
                'worker_lost',
                'waiting_for_worker_reconnect',
                'Task lease expired while the remote job may still be running.',
                attempt=attempt,
            )
        else:
            attempt.status = 'failed'
            attempt.finished_at = now
            task.assigned_worker_id = None
            task.lease_token = None
            task.lease_expires_at = None
            if task.attempt_count < task.max_attempts:
                task.next_attempt_at = now + _retry_delay(task.attempt_count)
                transition_task(
                    task,
                    'retry_wait',
                    'retry_wait',
                    'Task lease expired before remote submission; retry scheduled.',
                    attempt=attempt,
                )
            else:
                transition_task(
                    task,
                    'failed',
                    'failed',
                    'Task lease expired and no attempts remain.',
                    attempt=attempt,
                )
        refresh_batch_status(task.batch_id)
    db.session.commit()
    return len(expired)


def _resume_worker_lost_tasks(app, adapter_factory, asynchronous):
    resumed = 0
    now = utcnow()
    tasks = TrainingQueueTask.query.filter_by(status='worker_lost').order_by(
        TrainingQueueTask.id.asc()
    ).all()
    for task in tasks:
        attempt = TrainingJobAttempt.query.filter_by(
            task_id=task.id,
            attempt_number=task.attempt_count,
        ).first()
        if attempt is None or not attempt.remote_job_id:
            continue
        worker = db.session.get(TrainingWorker, task.assigned_worker_id)
        if (
            worker is not None
            and worker.status == 'online'
            and worker.enabled
        ):
            task.lease_token = attempt.lease_token
            task.lease_expires_at = now + _lease_duration()
            task.worker_lost_at = None
            task.recovery_deadline_at = None
            attempt.status = 'running'
            attempt.finished_at = None
            transition_task(
                task,
                'remote_running',
                'remote_running',
                'Worker reconnected; resuming remote job polling.',
                attempt=attempt,
            )
            db.session.commit()
            if _submit_task_pipeline(
                app,
                task,
                attempt,
                adapter_factory,
                asynchronous,
            ):
                resumed += 1
            continue

        if (
            task.recovery_deadline_at is None
            or task.recovery_deadline_at > now
            or task.resume_count >= task.max_resume_count
        ):
            continue
        try:
            store = checkpoint_store()
        except ObjectStoreError:
            continue
        checkpoint = _latest_resumable_checkpoint(task)
        if not store.enabled or checkpoint is None:
            continue
        try:
            stored_object = store.head(checkpoint.object_key)
        except ObjectStoreError:
            continue
        if stored_object.size_bytes != checkpoint.size_bytes:
            continue

        attempt.training_job_id = (
            attempt.training_job_id or task.training_job_id
        )
        attempt.status = 'abandoned'
        attempt.finished_at = now
        attempt.error = (
            'Original worker did not reconnect before the recovery deadline.'
        )
        task.resume_count += 1
        task.recovery_generation += 1
        task.max_attempts = max(
            task.max_attempts,
            task.attempt_count + 1,
        )
        task.assigned_worker_id = None
        task.training_job_id = None
        task.lease_token = None
        task.lease_expires_at = None
        task.worker_lost_at = None
        task.recovery_deadline_at = None
        task.next_attempt_at = now
        task.error = None
        transition_task(
            task,
            'resume_pending',
            'resume_pending',
            (
                f'Checkpoint epoch {checkpoint.epoch}/'
                f'{checkpoint.total_epochs} is ready for another worker.'
            ),
            attempt=attempt,
            details={
                'checkpoint_id': checkpoint.checkpoint_id,
                'checkpoint_epoch': checkpoint.epoch,
                'recovery_generation': task.recovery_generation,
            },
        )
        refresh_batch_status(task.batch_id)
        db.session.commit()
        resumed += 1
    return resumed


def _worker_supports_task(worker, task):
    capabilities = worker.capabilities or {}
    if capabilities.get('optimizer_contract_version') != 1:
        return False
    if task.status == 'resume_pending':
        try:
            store_enabled = checkpoint_store().enabled
        except ObjectStoreError:
            store_enabled = False
        if not (
            store_enabled
            and capabilities.get('checkpoint_upload')
            and capabilities.get('checkpoint_resume')
        ):
            return False
    training_mode = str(
        (task.request_payload or {}).get('training_mode') or 'fresh'
    )
    applies_parameter_set = bool(
        training_mode == 'finetune'
        or (task.request_payload or {}).get('apply_training_parameters')
    )
    if applies_parameter_set:
        if not capabilities.get('training_parameter_sets'):
            return False
        try:
            parameter_contract_version = int(
                capabilities.get('training_parameter_contract_version') or 0
            )
        except (TypeError, ValueError):
            return False
        if parameter_contract_version < TRAINING_PARAMETER_CONTRACT_VERSION:
            return False
        if (
            str(capabilities.get('training_parameter_catalog_hash') or '')
            != TRAINING_PARAMETER_CATALOG_HASH
        ):
            return False
    if training_mode == 'finetune':
        return worker_supports_finetune(worker)
    if not capabilities.get('training', True):
        return False

    worker_catalog_hash = capabilities.get('training_model_catalog_hash')
    if (
        worker_catalog_hash is not None
        and str(worker_catalog_hash) != TRAINING_MODEL_CATALOG_HASH
    ):
        return False

    model = str((task.request_payload or {}).get('model') or 'yolo11s.pt')
    allowed_models = capabilities.get('allowed_models')
    if allowed_models is None:
        return model == 'yolo11s.pt'
    if not isinstance(allowed_models, (list, tuple, set)):
        return False
    return model in {str(item) for item in allowed_models}


def dispatch_once(
    app,
    *,
    adapter_factory=adapter_for_worker,
    probe=True,
    asynchronous=True,
):
    with app.app_context():
        recover_expired_leases()
        if probe:
            probe_all_workers()
        resumed = _resume_worker_lost_tasks(
            app,
            adapter_factory,
            asynchronous,
        )

        online_workers = TrainingWorker.query.filter_by(
            enabled=True,
            status='online',
        ).order_by(TrainingWorker.id.asc()).all()
        workers = [
            worker
            for worker in online_workers
            if not worker.remote_active_job_id
        ]
        tasks = TrainingQueueTask.query.filter(
            TrainingQueueTask.status.in_(DISPATCHABLE_TASK_STATUSES),
            db.or_(
                TrainingQueueTask.next_attempt_at.is_(None),
                TrainingQueueTask.next_attempt_at <= utcnow(),
            ),
        ).order_by(
            TrainingQueueTask.priority.desc(),
            TrainingQueueTask.id.asc(),
        ).all()

        dispatched = 0
        for worker in workers:
            available_slots = max(worker.capacity - _active_lease_count(worker.id), 0)
            for _ in range(available_slots):
                if not tasks:
                    break
                compatible_index = next(
                    (
                        index
                        for index, queued_task in enumerate(tasks)
                        if _worker_supports_task(worker, queued_task)
                    ),
                    None,
                )
                if compatible_index is None:
                    break
                task = tasks.pop(compatible_index)
                attempt = _claim_task_for_worker(task, worker)
                if attempt is None:
                    continue
                refresh_batch_status(task.batch_id)
                db.session.commit()
                if _submit_task_pipeline(
                    app,
                    task,
                    attempt,
                    adapter_factory,
                    asynchronous,
                ):
                    dispatched += 1

        return {
            'dispatched': dispatched,
            'resumed': resumed,
            'online_workers': len(online_workers),
            'busy_workers': len(online_workers) - len(workers),
            'queued_tasks': len(tasks),
        }


def cancel_batch(batch):
    tasks = TrainingQueueTask.query.filter_by(batch_id=batch.id).all()
    blocked = []
    cancelled = 0
    for task in tasks:
        if task.status in TERMINAL_TASK_STATUSES:
            continue
        if task.status in ACTIVE_TASK_STATUSES | {'worker_lost'}:
            blocked.append(task.task_id)
            continue
        transition_task(
            task,
            'cancelled',
            'cancelled',
            'Task cancelled before remote execution.',
        )
        cancelled += 1
    refresh_batch_status(batch.id)
    if blocked:
        batch.status = 'cancelling'
    db.session.commit()
    return {'cancelled': cancelled, 'running_not_cancelled': blocked}


def retry_task(task):
    if task.status == 'worker_lost':
        raise ValueError(
            'The remote job may still be running. Reconnect its worker so the '
            'scheduler can resume the same remote job without duplication.'
        )
    if task.status not in {'failed', 'cancelled'}:
        raise ValueError('Only failed or cancelled tasks can be retried.')
    remote_attempt = TrainingJobAttempt.query.filter(
        TrainingJobAttempt.task_id == task.id,
        TrainingJobAttempt.remote_job_id.isnot(None),
    ).order_by(TrainingJobAttempt.attempt_number.desc()).first()
    if remote_attempt is not None:
        remote_job = TrainingJob.query.filter_by(
            remote_job_id=remote_attempt.remote_job_id
        ).first()
        if remote_job is None or remote_job.status != 'failed':
            raise ValueError(
                'A remote job already exists for this task. Adopt/reconcile '
                'that job instead of retrying to avoid duplicate training.'
            )
    previous_status = task.status
    task.status = 'retry_wait'
    task.stage = 'retry_wait'
    task.assigned_worker_id = None
    task.lease_token = None
    task.lease_expires_at = None
    task.next_attempt_at = utcnow()
    task.finished_at = None
    task.error = None
    if task.attempt_count >= task.max_attempts:
        task.max_attempts = task.attempt_count + 1
    record_task_event(
        task,
        'manual_retry',
        from_status=previous_status,
        to_status='retry_wait',
        message='Manual retry requested.',
    )
    refresh_batch_status(task.batch_id)
    db.session.commit()
    return task


def adopt_remote_job(
    task,
    worker,
    remote_job_id,
    adapter_factory=adapter_for_worker,
):
    if task.status in ACTIVE_TASK_STATUSES | {'worker_lost'}:
        raise ValueError('An active task cannot adopt another remote job.')
    if task.imported_model_id is not None or task.status == 'succeeded':
        raise ValueError('A completed task cannot adopt another remote job.')
    if worker is None or not worker.enabled:
        raise ValueError('The selected worker is unavailable.')

    normalized_job_id = normalize_remote_job_id(remote_job_id)
    duplicate_attempt = TrainingJobAttempt.query.filter(
        TrainingJobAttempt.remote_job_id == normalized_job_id,
        TrainingJobAttempt.task_id != task.id,
    ).first()
    if duplicate_attempt is not None:
        raise ValueError('The remote job is already assigned to another task.')

    remote_snapshot = adapter_factory(worker).get_job(normalized_job_id)
    if normalize_remote_job_id(remote_snapshot.get('job_id')) != normalized_job_id:
        raise WorkerApiError('Worker returned a different job during adoption.')

    task.attempt_count += 1
    task.max_attempts = max(task.max_attempts, task.attempt_count)
    lease_token = str(uuid.uuid4())
    attempt = TrainingJobAttempt(
        attempt_id=str(uuid.uuid4()),
        task_id=task.id,
        worker_id=worker.id,
        attempt_number=task.attempt_count,
        status='worker_lost',
        lease_token=lease_token,
        remote_job_id=normalized_job_id,
        heartbeat_at=utcnow(),
    )
    db.session.add(attempt)
    db.session.flush()

    task.assigned_worker_id = worker.id
    task.lease_token = lease_token
    task.lease_expires_at = utcnow() + _lease_duration()
    task.next_attempt_at = None
    task.finished_at = None
    task.error = None
    _sync_local_training_job(task, worker, remote_snapshot)
    transition_task(
        task,
        'worker_lost',
        'waiting_for_worker_reconnect',
        f'Adopted remote job {normalized_job_id}; reconciliation scheduled.',
        attempt=attempt,
        details={
            'remote_job_id': normalized_job_id,
            'worker_id': worker.worker_id,
        },
    )
    refresh_batch_status(task.batch_id)
    db.session.commit()
    return attempt


def scheduler_status():
    try:
        store = checkpoint_store()
        object_store_status = {
            'backend': store.backend_name,
            'enabled': bool(store.enabled),
            'error': None,
        }
    except ObjectStoreError as exc:
        object_store_status = {
            'backend': 'error',
            'enabled': False,
            'error': str(exc),
        }
    return {
        'object_store': object_store_status,
        'workers': {
            'total': TrainingWorker.query.count(),
            'online': TrainingWorker.query.filter_by(
                enabled=True,
                status='online',
            ).count(),
        },
        'tasks': {
            'queued': TrainingQueueTask.query.filter(
                TrainingQueueTask.status.in_(DISPATCHABLE_TASK_STATUSES)
            ).count(),
            'active': TrainingQueueTask.query.filter(
                TrainingQueueTask.status.in_(ACTIVE_TASK_STATUSES)
            ).count(),
            'worker_lost': TrainingQueueTask.query.filter_by(
                status='worker_lost'
            ).count(),
            'succeeded': TrainingQueueTask.query.filter_by(
                status='succeeded'
            ).count(),
            'failed': TrainingQueueTask.query.filter_by(status='failed').count(),
        },
        'batches': {
            'total': TrainingBatch.query.count(),
            'running': TrainingBatch.query.filter_by(status='running').count(),
        },
    }


def run_scheduler_forever(app, stop_event=None):
    interval = max(
        float(app.config.get('TRAINING_SCHEDULER_INTERVAL_SECONDS', 5)),
        0.5,
    )
    while stop_event is None or not stop_event.is_set():
        try:
            dispatch_once(app, asynchronous=True)
        except Exception:
            app.logger.exception('Training scheduler tick failed')
        if stop_event is not None:
            stop_event.wait(interval)
        else:
            time.sleep(interval)
