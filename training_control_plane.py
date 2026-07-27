import hashlib
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from requests_toolbelt.multipart.encoder import MultipartEncoder

from models import (
    db,
    AIModel,
    Project,
    TrainingBatch,
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


WORKER_PROVIDERS = {'colab_http'}
WORKER_STATUSES = {'online', 'offline', 'draining', 'disabled'}
ACTIVE_TASK_STATUSES = {
    'preparing_dataset',
    'uploading_dataset',
    'submitting',
    'remote_queued',
    'remote_running',
    'downloading_artifacts',
    'importing_model',
}
DISPATCHABLE_TASK_STATUSES = {'queued', 'waiting_for_worker', 'retry_wait'}
TERMINAL_TASK_STATUSES = {'succeeded', 'failed', 'cancelled'}
REMOTE_TERMINAL_STATUSES = {'succeeded', 'failed'}

_executor = ThreadPoolExecutor(
    max_workers=max(int(os.environ.get('TOOLIB_TRAINING_EXECUTOR_SIZE', '8')), 1),
    thread_name_prefix='toolib-training',
)
_running_task_ids = set()
_running_task_lock = threading.Lock()


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
                'max_concurrent_jobs': 1,
                'idempotent_submit': bool(payload.get('idempotent_submit', False)),
            },
        }

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

    def download_artifact(self, remote_job_id, artifact_kind, destination):
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_suffix(destination.suffix + '.part')
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
                with temporary_path.open('wb') as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
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


def create_training_batch(payload):
    jobs_payload = payload.get('jobs')
    if not isinstance(jobs_payload, list) or not jobs_payload:
        raise ValueError('jobs must be a non-empty JSON array.')
    if len(jobs_payload) > 100:
        raise ValueError('A training batch can contain at most 100 jobs.')

    name = str(payload.get('name') or '').strip()
    if not name:
        name = f'Training batch {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    max_attempts_default = int(payload.get('max_attempts') or 3)
    if not 1 <= max_attempts_default <= 10:
        raise ValueError('max_attempts must be between 1 and 10.')

    batch = TrainingBatch(
        batch_id=str(uuid.uuid4()),
        name=name[:160],
        status='queued',
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

        model = str(raw_job.get('model') or 'yolo11n.pt').strip()
        epochs = int(raw_job.get('epochs') or 1)
        batch_size = int(raw_job.get('batch') or 16)
        imgsz = int(raw_job.get('imgsz') or 640)
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

        task = TrainingQueueTask(
            task_id=task_uuid,
            idempotency_key=idempotency_key,
            batch_id=batch.id,
            project_id=project_id,
            status='queued',
            stage='queued',
            priority=int(raw_job.get('priority') or 0),
            request_payload={
                'model': model[:100],
                'epochs': epochs,
                'batch': batch_size,
                'imgsz': imgsz,
            },
            dataset_config={
                'splits': normalized_splits,
                'include_unlabeled': include_unlabeled,
                'exclude_flagged': exclude_flagged,
            },
            max_attempts=max_attempts,
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


def _lease_duration():
    seconds = int(current_app.config.get('TRAINING_TASK_LEASE_SECONDS', 300))
    return timedelta(seconds=max(seconds, 30))


def _retry_delay(attempt_count):
    base_seconds = int(current_app.config.get('TRAINING_RETRY_BASE_SECONDS', 15))
    maximum_seconds = int(current_app.config.get('TRAINING_RETRY_MAX_SECONDS', 900))
    return timedelta(
        seconds=min(base_seconds * (2 ** max(attempt_count - 1, 0)), maximum_seconds)
    )


def _claim_task_for_worker(task, worker):
    if task.status not in DISPATCHABLE_TASK_STATUSES:
        return None
    if task.next_attempt_at and task.next_attempt_at > utcnow():
        return None
    if _active_lease_count(worker.id) >= worker.capacity:
        return None

    lease_token = str(uuid.uuid4())
    task.attempt_count += 1
    task.assigned_worker_id = worker.id
    task.lease_token = lease_token
    task.lease_expires_at = utcnow() + _lease_duration()
    task.next_attempt_at = None
    task.error = None
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
    generation = failed_remote_jobs + 1
    key_digest = hashlib.sha256(
        task.idempotency_key.encode('utf-8')
    ).hexdigest()[:16]
    return f'toolib:{task.task_id}:run:{generation}:{key_digest}'


def _import_task_model(task, job, onnx_path):
    if task.imported_model_id is not None:
        model = db.session.get(AIModel, task.imported_model_id)
        if model is not None:
            return model

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
        temporary_path = destination.with_suffix('.onnx.part')
        shutil.copy2(onnx_path, temporary_path)
        temporary_path.replace(destination)
        existing = AIModel(
            name=f'Automated {job.model or "YOLO"} - {task.task_id[:8]}',
            description=(
                f'Phase 5 task {task.task_id}; remote job {job.remote_job_id}; '
                f'epochs={job.epochs}; batch={job.batch}; imgsz={job.imgsz}'
            ),
            filename=filename,
            model_type='detection',
            is_active=False,
            activation_ready=False,
        )
        db.session.add(existing)
        db.session.flush()

    task.imported_model_id = existing.id
    job.imported_model_id = existing.id
    return existing


def _renew_lease(task, attempt):
    task.lease_expires_at = utcnow() + _lease_duration()
    attempt.heartbeat_at = utcnow()


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
        attempt.status = 'worker_lost'
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
                transition_task(
                    task,
                    'uploading_dataset',
                    'uploading_dataset',
                    f'Uploading dataset {dataset.dataset_id} to {worker.name}.',
                    attempt=attempt,
                )
                _renew_lease(task, attempt)
                db.session.commit()
                remote_dataset = adapter.upload_dataset(dataset)
                dataset.status = 'uploaded'
                dataset.remote_api_url = worker.api_url
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
                submit_payload = dict(task.request_payload or {})
                submit_payload['dataset_id'] = dataset.dataset_id
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

            transition_task(
                task,
                'downloading_artifacts',
                'downloading_artifacts',
                'Downloading ONNX artifact into the central artifact store.',
                attempt=attempt,
            )
            db.session.commit()
            onnx_path = artifact_store().artifact_path(task.task_id, 'onnx')
            adapter.download_artifact(job.remote_job_id, 'onnx', onnx_path)
            if not onnx_path.is_file() or onnx_path.stat().st_size <= 0:
                raise WorkerApiError('Downloaded ONNX artifact is empty.')

            transition_task(
                task,
                'importing_model',
                'importing_model',
                'Importing candidate model as inactive.',
                attempt=attempt,
            )
            db.session.commit()
            model = _import_task_model(task, job, onnx_path)
            attempt.status = 'succeeded'
            attempt.finished_at = utcnow()
            task.error = None
            transition_task(
                task,
                'succeeded',
                'succeeded',
                f'Imported inactive model #{model.id}.',
                attempt=attempt,
                details={
                    'model_id': model.id,
                    'remote_job_id': job.remote_job_id,
                    'onnx_sha256': sha256_path(onnx_path),
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
    tasks = TrainingQueueTask.query.filter_by(status='worker_lost').order_by(
        TrainingQueueTask.id.asc()
    ).all()
    for task in tasks:
        worker = db.session.get(TrainingWorker, task.assigned_worker_id)
        if worker is None or worker.status != 'online' or not worker.enabled:
            continue
        attempt = TrainingJobAttempt.query.filter_by(
            task_id=task.id,
            attempt_number=task.attempt_count,
        ).first()
        if attempt is None or not attempt.remote_job_id:
            continue
        task.lease_token = attempt.lease_token
        task.lease_expires_at = utcnow() + _lease_duration()
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
    return resumed


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
                task = tasks.pop(0)
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
    return {
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
