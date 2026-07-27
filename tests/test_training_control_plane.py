import os
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from models import (
    db,
    AIModel,
    Project,
    TrainingBatch,
    TrainingJobAttempt,
    TrainingQueueTask,
    TrainingWorker,
)
from test_helpers import create_isolated_test_app
from training_control_plane import (
    WorkerUnavailableError,
    create_training_batch,
    dispatch_once,
    encrypt_worker_token,
)


class FakeWorkerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.submissions = {}
        self.submit_count = 0
        self.active_uploads = 0
        self.max_active_uploads = 0
        self.fail_status_once = False

    def begin_upload(self):
        with self.lock:
            self.active_uploads += 1
            self.max_active_uploads = max(
                self.max_active_uploads,
                self.active_uploads,
            )

    def end_upload(self):
        with self.lock:
            self.active_uploads -= 1


class FakeWorkerAdapter:
    def __init__(self, worker, state):
        self.worker = worker
        self.state = state

    def upload_dataset(self, dataset):
        self.state.begin_upload()
        try:
            time.sleep(0.08)
            return {
                'status': 'uploaded',
                'dataset_id': dataset.dataset_id,
                'sha256': dataset.archive_sha256,
                'drive_path': f'/fake/{self.worker.worker_id}/{dataset.dataset_id}',
            }
        finally:
            self.state.end_upload()

    def submit_job(self, request_payload, idempotency_key):
        with self.state.lock:
            remote_job_id = self.state.submissions.get(idempotency_key)
            if remote_job_id is None:
                remote_job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
                self.state.submissions[idempotency_key] = remote_job_id
                self.state.submit_count += 1
        return {
            'job_id': remote_job_id,
            'status': 'queued',
            **request_payload,
            'total_epochs': request_payload['epochs'],
        }

    def get_job(self, remote_job_id):
        with self.state.lock:
            if self.state.fail_status_once:
                self.state.fail_status_once = False
                raise WorkerUnavailableError('simulated worker disconnect')
        return {
            'job_id': remote_job_id,
            'status': 'succeeded',
            'model': 'yolo11n.pt',
            'epochs': 1,
            'batch': 4,
            'imgsz': 640,
            'current_epoch': 1,
            'total_epochs': 1,
            'message': 'Training and ONNX export completed.',
            'artifacts': {'onnx': f'/fake/{remote_job_id}/best.onnx'},
        }

    def download_artifact(self, remote_job_id, artifact_kind, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f'{remote_job_id}:{artifact_kind}'.encode('utf-8'))
        return destination


class TestTrainingControlPlane:
    def setup_method(self):
        import tempfile

        self.temp_dir = tempfile.TemporaryDirectory(
            prefix='toolib_training_control_plane_'
        )
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / 'control_plane.db'
        self.dataset_root = self.root / 'datasets'
        self.artifact_root = self.root / 'artifacts'
        self.model_root = self.root / 'models'
        self.credential_key = Fernet.generate_key().decode('ascii')
        self.app = create_isolated_test_app(
            str(self.db_path),
            TOOLIB_WORKER_CREDENTIAL_KEY=self.credential_key,
            TRAINING_DATASET_ROOT=str(self.dataset_root),
            TRAINING_ARTIFACT_ROOT=str(self.artifact_root),
            MODEL_STORAGE_ROOT=str(self.model_root),
            TRAINING_REMOTE_POLL_SECONDS=0,
            TRAINING_REMOTE_MAX_SECONDS=60,
            TRAINING_TASK_LEASE_SECONDS=60,
            TRAINING_RETRY_BASE_SECONDS=0,
            TRAINING_CLEAR_HEADER_CALLBACK=lambda _path: ['train', 'val'],
        )
        self.client = self.app.test_client()
        self.project_ids = []
        with self.app.app_context():
            for index in range(3):
                project_root = self.root / f'project-{index}'
                project_root.mkdir()
                (project_root / 'classes.txt').write_text(
                    'bottle\ncap\n',
                    encoding='utf-8',
                )
                project = Project(
                    name=f'Project {index}',
                    root_path=str(project_root),
                )
                db.session.add(project)
                db.session.flush()
                self.project_ids.append(project.id)
            db.session.commit()

        self.export_patch = mock.patch(
            'training_dataset_service.utils.export_dataset',
            side_effect=self.fake_export_dataset,
        )
        self.export_patch.start()

    def teardown_method(self):
        self.export_patch.stop()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.app.app_context():
                active = TrainingQueueTask.query.filter(
                    TrainingQueueTask.status.in_({
                        'preparing_dataset',
                        'uploading_dataset',
                        'submitting',
                        'remote_queued',
                        'remote_running',
                        'downloading_artifacts',
                        'importing_model',
                    })
                ).count()
            if active == 0:
                break
            time.sleep(0.05)
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def fake_export_dataset(criteria, splits=None, format='yolo', output_dir=None):
        assert format == 'yolo'
        assert criteria['project_ids']
        export_root = Path(output_dir)
        for split in ('train', 'val'):
            (export_root / 'images' / split).mkdir(parents=True, exist_ok=True)
            (export_root / 'labels' / split).mkdir(parents=True, exist_ok=True)
        for split, count in (('train', 4), ('val', 1)):
            for index in range(count):
                stem = f'{split}-{index}'
                (export_root / 'images' / split / f'{stem}.jpg').write_bytes(
                    b'image'
                )
                (export_root / 'labels' / split / f'{stem}.txt').write_text(
                    '0 0.5 0.5 0.2 0.2\n',
                    encoding='utf-8',
                )
        (export_root / 'data.yaml').write_text(
            'path: .\ntrain: images/train\nval: images/val\n',
            encoding='utf-8',
        )
        return {
            'status': 'success',
            'stats': {
                'total': 5,
                'unlabeled': 0,
                'train': 4,
                'val': 1,
                'test': 0,
            },
        }

    def add_worker(self, name):
        with self.app.app_context():
            worker = TrainingWorker(
                worker_id=str(uuid.uuid4()),
                name=name,
                provider='colab_http',
                api_url=f'https://{name.lower()}.trycloudflare.com',
                token_ciphertext=encrypt_worker_token(f'{name}-secret-token'),
                status='online',
                enabled=True,
                capacity=1,
                gpu_available=True,
                gpu_name='Fake GPU',
                capabilities={'max_concurrent_jobs': 1},
            )
            db.session.add(worker)
            db.session.commit()
            return worker.id

    def create_batch(self, project_ids=None):
        project_ids = project_ids or self.project_ids
        with self.app.app_context():
            batch, _tasks = create_training_batch({
                'name': 'Phase 5 batch',
                'jobs': [
                    {
                        'project_id': project_id,
                        'model': 'yolo11n.pt',
                        'epochs': 1,
                        'batch': 4,
                        'imgsz': 640,
                    }
                    for project_id in project_ids
                ],
            })
            return batch.id

    def wait_for_terminal_count(self, expected, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.app.app_context():
                count = TrainingQueueTask.query.filter(
                    TrainingQueueTask.status.in_({'succeeded', 'failed'})
                ).count()
            if count >= expected:
                return
            time.sleep(0.05)
        raise AssertionError(f'Timed out waiting for {expected} terminal tasks.')

    def test_worker_registration_encrypts_token_and_never_serializes_it(self):
        health = {
            'status': 'online',
            'gpu_available': True,
            'gpu_name': 'T4',
            'capabilities': {'max_concurrent_jobs': 1},
        }
        with mock.patch(
            'routes.ColabHttpWorkerAdapter.health',
            return_value=health,
        ):
            response = self.client.post('/api/training-workers', json={
                'name': 'Colab T4',
                'provider': 'colab_http',
                'api_url': 'https://worker-token-test.trycloudflare.com',
                'api_token': 'plain-secret-token',
            })

        assert response.status_code == 201, response.get_data(as_text=True)
        body = response.get_json()
        assert body['status'] == 'online'
        assert body['credentials_configured'] is True
        assert 'token' not in body
        with self.app.app_context():
            worker = TrainingWorker.query.one()
            assert worker.token_ciphertext != 'plain-secret-token'
            assert 'plain-secret-token' not in worker.token_ciphertext

    def test_strict_credential_mode_fails_closed_without_external_key(self):
        strict_db_path = self.root / 'strict-credentials.db'
        strict_app = create_isolated_test_app(
            str(strict_db_path),
            TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY=True,
        )
        with mock.patch.dict(
            os.environ,
            {'TOOLIB_WORKER_CREDENTIAL_KEY': ''},
        ):
            with strict_app.app_context():
                with mock.patch(
                    'routes.ColabHttpWorkerAdapter.health',
                    return_value={
                        'status': 'online',
                        'gpu_available': True,
                        'capabilities': {'max_concurrent_jobs': 1},
                    },
                ):
                    response = strict_app.test_client().post(
                        '/api/training-workers',
                        json={
                            'name': 'Strict worker',
                            'api_url': 'https://strict.trycloudflare.com',
                            'api_token': 'must-not-fallback',
                        },
                    )

                assert response.status_code == 502
                assert 'must be configured' in response.get_json()['error']
                assert TrainingWorker.query.count() == 0
                db.session.remove()
                db.engine.dispose()

    def test_worker_reconnect_rotates_endpoint_and_encrypted_token_in_place(self):
        worker_id = self.add_worker('WorkerRotate')
        health = {
            'status': 'online',
            'gpu_available': True,
            'gpu_name': 'L4',
            'capabilities': {'max_concurrent_jobs': 1},
        }
        with mock.patch(
            'routes.ColabHttpWorkerAdapter.health',
            return_value=health,
        ):
            response = self.client.put(
                f'/api/training-workers/{worker_id}',
                json={
                    'api_url': 'https://new-worker.trycloudflare.com',
                    'api_token': 'rotated-secret-token',
                    'capacity': 1,
                },
            )

        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert body['id'] == worker_id
        assert body['api_url'] == 'https://new-worker.trycloudflare.com'
        assert 'token' not in body
        with self.app.app_context():
            worker = db.session.get(TrainingWorker, worker_id)
            assert worker.token_ciphertext != 'rotated-secret-token'
            assert 'rotated-secret-token' not in worker.token_ciphertext

    def test_two_workers_process_three_tasks_with_real_parallel_overlap(self):
        self.add_worker('WorkerA')
        self.add_worker('WorkerB')
        batch_id = self.create_batch()
        state = FakeWorkerState()

        result = dispatch_once(
            self.app,
            adapter_factory=lambda worker: FakeWorkerAdapter(worker, state),
            probe=False,
            asynchronous=True,
        )
        assert result['dispatched'] == 2
        self.wait_for_terminal_count(2)

        with self.app.app_context():
            statuses = [
                task.status
                for task in TrainingQueueTask.query.order_by(
                    TrainingQueueTask.id.asc()
                ).all()
            ]
            assert statuses.count('succeeded') == 2
            assert statuses.count('queued') == 1
            assert AIModel.query.count() == 2
            assert AIModel.query.filter_by(is_active=True).count() == 0

        second = dispatch_once(
            self.app,
            adapter_factory=lambda worker: FakeWorkerAdapter(worker, state),
            probe=False,
            asynchronous=True,
        )
        assert second['dispatched'] == 1
        self.wait_for_terminal_count(3)

        with self.app.app_context():
            batch = db.session.get(TrainingBatch, batch_id)
            assert batch.status == 'succeeded'
            assert batch.succeeded_jobs == 3
            assert TrainingJobAttempt.query.count() == 3
            assert AIModel.query.count() == 3
            assert all(
                model.activation_ready is False
                for model in AIModel.query.all()
            )
        assert state.max_active_uploads >= 2

    def test_worker_disconnect_resumes_same_remote_job_without_resubmit(self):
        self.add_worker('WorkerReconnect')
        self.create_batch(project_ids=[self.project_ids[0]])
        state = FakeWorkerState()
        state.fail_status_once = True
        factory = lambda worker: FakeWorkerAdapter(worker, state)

        first = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert first['dispatched'] == 1
        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            attempt = TrainingJobAttempt.query.one()
            assert task.status == 'worker_lost'
            assert attempt.remote_job_id
            assert state.submit_count == 1

        second = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert second['resumed'] == 1
        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            assert task.status == 'succeeded'
            assert task.imported_model_id is not None
            assert state.submit_count == 1

    def test_remote_acceptance_survives_local_sync_failure_without_resubmit(self):
        self.add_worker('WorkerDurableAcceptance')
        self.create_batch(project_ids=[self.project_ids[0]])
        state = FakeWorkerState()
        factory = lambda worker: FakeWorkerAdapter(worker, state)

        with mock.patch(
            'training_control_plane._sync_local_training_job',
            side_effect=RuntimeError('simulated local constraint failure'),
        ):
            first = dispatch_once(
                self.app,
                adapter_factory=factory,
                probe=False,
                asynchronous=False,
            )

        assert first['dispatched'] == 1
        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            attempt = TrainingJobAttempt.query.one()
            assert task.status == 'worker_lost'
            assert attempt.remote_job_id
            assert state.submit_count == 1

        second = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )

        assert second['resumed'] == 1
        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            assert task.status == 'succeeded'
            assert state.submit_count == 1

    def test_ambiguous_submit_retry_uses_same_idempotency_key(self):
        self.add_worker('WorkerAmbiguousSubmit')
        self.create_batch(project_ids=[self.project_ids[0]])
        state = FakeWorkerState()
        failed_after_acceptance = [False]

        class AmbiguousSubmitAdapter(FakeWorkerAdapter):
            def submit_job(self, request_payload, idempotency_key):
                response = super().submit_job(
                    request_payload,
                    idempotency_key,
                )
                if not failed_after_acceptance[0]:
                    failed_after_acceptance[0] = True
                    raise WorkerUnavailableError(
                        'connection closed after remote acceptance'
                    )
                return response

        def factory(worker):
            return AmbiguousSubmitAdapter(worker, state)

        first = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert first['dispatched'] == 1
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'retry_wait'
            assert state.submit_count == 1

        second = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert second['dispatched'] == 1
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'succeeded'
            assert state.submit_count == 1

    def test_confirmed_remote_failure_uses_new_idempotency_generation(self):
        self.add_worker('WorkerConfirmedFailure')
        self.create_batch(project_ids=[self.project_ids[0]])
        state = FakeWorkerState()
        first_remote_job_id = [None]

        class FailFirstRemoteJobAdapter(FakeWorkerAdapter):
            def submit_job(self, request_payload, idempotency_key):
                response = super().submit_job(
                    request_payload,
                    idempotency_key,
                )
                if first_remote_job_id[0] is None:
                    first_remote_job_id[0] = response['job_id']
                return response

            def get_job(self, remote_job_id):
                if remote_job_id == first_remote_job_id[0]:
                    return {
                        'job_id': remote_job_id,
                        'status': 'failed',
                        'model': 'yolo11n.pt',
                        'epochs': 1,
                        'batch': 4,
                        'imgsz': 640,
                        'current_epoch': 0,
                        'total_epochs': 1,
                        'message': 'simulated confirmed training failure',
                        'error': 'simulated confirmed training failure',
                        'artifacts': None,
                    }
                return super().get_job(remote_job_id)

        factory = lambda worker: FailFirstRemoteJobAdapter(worker, state)
        first = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert first['dispatched'] == 1
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'retry_wait'
            assert state.submit_count == 1

        second = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert second['dispatched'] == 1
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'succeeded'
            assert state.submit_count == 2

    def test_remote_busy_worker_is_not_dispatched(self):
        worker_id = self.add_worker('WorkerBusy')
        self.create_batch(project_ids=[self.project_ids[0]])
        with self.app.app_context():
            worker = db.session.get(TrainingWorker, worker_id)
            worker.remote_active_job_id = str(uuid.uuid4())
            db.session.commit()

        result = dispatch_once(
            self.app,
            adapter_factory=lambda worker: FakeWorkerAdapter(
                worker,
                FakeWorkerState(),
            ),
            probe=False,
            asynchronous=False,
        )

        assert result['dispatched'] == 0
        assert result['busy_workers'] == 1
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'queued'

    def test_deleting_training_history_clears_queue_reference(self):
        self.add_worker('WorkerDeleteHistory')
        self.create_batch(project_ids=[self.project_ids[0]])
        state = FakeWorkerState()
        dispatch_once(
            self.app,
            adapter_factory=lambda worker: FakeWorkerAdapter(worker, state),
            probe=False,
            asynchronous=False,
        )

        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            job_id = task.training_job_id
            assert task.status == 'succeeded'
            assert job_id is not None

        response = self.client.delete(f'/api/training-jobs/{job_id}')

        assert response.status_code == 200
        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            assert task.training_job_id is None

    def test_queue_survives_new_app_instance_using_same_database(self):
        batch_id = self.create_batch(project_ids=[self.project_ids[0]])
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

        second_app = create_isolated_test_app(
            str(self.db_path),
            TOOLIB_WORKER_CREDENTIAL_KEY=self.credential_key,
            TRAINING_DATASET_ROOT=str(self.dataset_root),
            TRAINING_ARTIFACT_ROOT=str(self.artifact_root),
            MODEL_STORAGE_ROOT=str(self.model_root),
        )
        with second_app.app_context():
            batch = db.session.get(TrainingBatch, batch_id)
            task = TrainingQueueTask.query.one()
            assert batch.status == 'queued'
            assert task.status == 'queued'
            assert task.idempotency_key
            db.session.remove()
            db.engine.dispose()

    def test_cancel_batch_only_cancels_tasks_not_started_remotely(self):
        batch_id = self.create_batch(project_ids=[self.project_ids[0]])
        response = self.client.post(f'/api/training-batches/{batch_id}/cancel')
        assert response.status_code == 200
        body = response.get_json()
        assert body['cancelled'] == 1
        assert body['running_not_cancelled'] == []
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'cancelled'

    def test_batch_rejects_idempotency_key_that_would_be_truncated(self):
        response = self.client.post('/api/training-batches', json={
            'name': 'Unsafe idempotency key',
            'jobs': [{
                'project_id': self.project_ids[0],
                'idempotency_key': 'x' * 101,
            }],
        })

        assert response.status_code == 400
        assert 'at most 100 characters' in response.get_json()['error']
        with self.app.app_context():
            assert TrainingBatch.query.count() == 0
            assert TrainingQueueTask.query.count() == 0

    def test_worker_lost_manual_retry_is_blocked_to_prevent_duplicate_remote_job(self):
        self.add_worker('WorkerReconnectOnly')
        self.create_batch(project_ids=[self.project_ids[0]])
        state = FakeWorkerState()
        state.fail_status_once = True

        dispatch_once(
            self.app,
            adapter_factory=lambda worker: FakeWorkerAdapter(worker, state),
            probe=False,
            asynchronous=False,
        )
        with self.app.app_context():
            task = TrainingQueueTask.query.one()
            task_id = task.id
            assert task.status == 'worker_lost'
            assert state.submit_count == 1

        response = self.client.post(
            f'/api/training-queue-tasks/{task_id}/retry'
        )

        assert response.status_code == 409
        assert 'Reconnect its worker' in response.get_json()['error']
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'worker_lost'
            assert state.submit_count == 1
