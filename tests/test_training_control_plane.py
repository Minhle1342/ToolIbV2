import os
import hashlib
import io
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from models import (
    db,
    AIModel,
    FineTuneParameterSet,
    ModelArtifact,
    Project,
    TrainingBatch,
    TrainingDataset,
    TrainingJobAttempt,
    TrainingQueueTask,
    TrainingWorker,
)
from test_helpers import create_isolated_test_app
from training_control_plane import (
    ColabHttpWorkerAdapter,
    WorkerUnavailableError,
    create_finetune_experiment,
    create_training_batch,
    dispatch_once,
    encrypt_worker_token,
    recover_expired_leases,
    utcnow,
)


class FakeWorkerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.submissions = {}
        self.requests_by_job = {}
        self.submit_count = 0
        self.model_upload_count = 0
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

    def upload_model_artifact(self, artifact):
        with self.state.lock:
            self.state.model_upload_count += 1
        return {
            'status': 'existing',
            'artifact_id': artifact.artifact_id,
            'sha256': artifact.sha256,
            'task': 'detect',
            'class_names': ['bottle', 'cap'],
            'drive_path': f'/fake/models/{artifact.artifact_id}/parent.pt',
        }

    def submit_job(self, request_payload, idempotency_key):
        with self.state.lock:
            remote_job_id = self.state.submissions.get(idempotency_key)
            if remote_job_id is None:
                remote_job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
                self.state.submissions[idempotency_key] = remote_job_id
                self.state.submit_count += 1
            self.state.requests_by_job[remote_job_id] = dict(request_payload)
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
        request_payload = self.state.requests_by_job.get(remote_job_id, {})
        is_finetune = request_payload.get('training_mode') == 'finetune'
        artifacts = {'onnx': f'/fake/{remote_job_id}/best.onnx'}
        metrics = {}
        if is_finetune:
            artifacts.update({
                'pt': f'/fake/{remote_job_id}/best.pt',
                'last_pt': f'/fake/{remote_job_id}/last.pt',
                'manifest': f'/fake/{remote_job_id}/manifest.json',
                'results': f'/fake/{remote_job_id}/results.csv',
                'args': f'/fake/{remote_job_id}/args.yaml',
            })
            metrics = {'metrics/mAP50-95(B)': 0.42}
        return {
            'job_id': remote_job_id,
            'status': 'succeeded',
            'model': request_payload.get('model', 'yolo11n.pt'),
            'epochs': request_payload.get('epochs', 1),
            'batch': request_payload.get('batch', 4),
            'imgsz': request_payload.get('imgsz', 640),
            'current_epoch': request_payload.get('epochs', 1),
            'total_epochs': request_payload.get('epochs', 1),
            'message': 'Training and ONNX export completed.',
            'artifacts': artifacts,
            'metrics': metrics,
        }

    def download_artifact(
        self,
        remote_job_id,
        artifact_kind,
        destination,
        progress_callback=None,
    ):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = f'{remote_job_id}:{artifact_kind}'.encode('utf-8')
        if progress_callback is not None:
            progress_callback(0, len(content))
        destination.write_bytes(content)
        if progress_callback is not None:
            progress_callback(len(content), len(content))
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
        self.parent_artifact_root = self.root / 'parent-artifacts'
        self.credential_key = Fernet.generate_key().decode('ascii')
        self.app = create_isolated_test_app(
            str(self.db_path),
            TOOLIB_WORKER_CREDENTIAL_KEY=self.credential_key,
            TRAINING_DATASET_ROOT=str(self.dataset_root),
            TRAINING_ARTIFACT_ROOT=str(self.artifact_root),
            MODEL_STORAGE_ROOT=str(self.model_root),
            MODEL_ARTIFACT_ROOT=str(self.parent_artifact_root),
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
                capabilities={
                    'training': True,
                    'training_modes': ['fresh', 'finetune'],
                    'dataset_upload': True,
                    'model_artifact_upload': True,
                    'artifact_download': [
                        'onnx',
                        'pt',
                        'last_pt',
                        'manifest',
                        'results',
                        'args',
                    ],
                    'max_concurrent_jobs': 1,
                },
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

    def create_parent_model(self, class_names=None):
        class_names = class_names or ['bottle', 'cap']
        with self.app.app_context():
            checkpoint_path = self.root / f'parent-{uuid.uuid4().hex}.pt'
            checkpoint_path.write_bytes(b'trusted-owner-checkpoint')
            model = AIModel(
                name='External parent',
                filename=f'external_{uuid.uuid4().hex[:12]}.pt',
                model_type='detection',
                is_active=False,
                activation_ready=False,
                source_kind='external_pt',
                finetune_status='ready',
                class_names=class_names,
            )
            db.session.add(model)
            db.session.flush()
            artifact = ModelArtifact(
                artifact_id=str(uuid.uuid4()),
                model_id=model.id,
                kind='parent_pt',
                storage_path=str(checkpoint_path),
                sha256=hashlib.sha256(
                    checkpoint_path.read_bytes()
                ).hexdigest(),
                size_bytes=checkpoint_path.stat().st_size,
            )
            db.session.add(artifact)
            db.session.commit()
            return model.id

    def active_parameter_set_ids(self, count=None):
        response = self.client.get('/api/finetune/config')
        assert response.status_code == 200, response.get_data(as_text=True)
        parameter_sets = [
            parameter_set
            for parameter_set in response.get_json()['parameter_sets']
            if parameter_set['is_active']
        ]
        if count is not None:
            parameter_sets = parameter_sets[:count]
        return [parameter_set['id'] for parameter_set in parameter_sets]

    def test_external_pt_upload_is_stored_without_web_process_deserialization(self):
        response = self.client.post(
            '/api/finetune-models',
            data={
                'name': 'Owner checkpoint',
                'file': (
                    io.BytesIO(b'trusted-owner-checkpoint'),
                    'V14.7.pt',
                ),
            },
            content_type='multipart/form-data',
        )
        assert response.status_code == 201, response.get_data(as_text=True)
        imported = response.get_json()
        assert imported['source_kind'] == 'external_pt'
        assert imported['finetune_status'] == 'pending_validation'
        assert imported['activation_ready'] is False
        assert imported['filename'].endswith('.pt')
        assert imported['artifacts'][0]['kind'] == 'parent_pt'

        worker_id = self.add_worker('ValidationWorker')
        artifact = imported['artifacts'][0]
        with mock.patch(
            'training_control_plane.ColabHttpWorkerAdapter.upload_model_artifact',
            return_value={
                'status': 'uploaded',
                'artifact_id': artifact['artifact_id'],
                'sha256': artifact['sha256'],
                'task': 'detect',
                'class_names': ['bottle', 'cap'],
            },
        ):
            validated = self.client.post(
                f"/api/finetune-models/{imported['id']}/validate",
                json={'worker_id': worker_id},
            )
        assert validated.status_code == 200, validated.get_data(as_text=True)
        body = validated.get_json()
        assert body['finetune_status'] == 'ready'
        assert body['fine_tune_eligible'] is True
        assert body['class_names'] == ['bottle', 'cap']

    def test_finetune_parameter_set_crud_clone_archive_restore_and_delete(self):
        config = self.client.get('/api/finetune/config')
        assert config.status_code == 200
        seeded = config.get_json()['parameter_sets']
        assert len(seeded) == 5
        assert all(parameter_set['is_system'] for parameter_set in seeded)

        created_response = self.client.post(
            '/api/finetune-parameter-sets',
            json={
                'name': 'Two epoch smoke',
                'description': 'Fast end-to-end validation.',
                'parameters': {
                    'epochs': 2,
                    'batch': 4,
                    'imgsz': 640,
                    'lr0': 0.00008,
                    'freeze': 8,
                },
            },
        )
        assert created_response.status_code == 201
        created = created_response.get_json()
        assert created['version'] == 1
        assert created['parameters']['epochs'] == 2
        assert created['parameters']['lrf'] == 0.01
        assert created['can_delete'] is True

        updated_response = self.client.patch(
            f"/api/finetune-parameter-sets/{created['id']}",
            json={
                'parameters': {
                    'lr0': 0.00004,
                },
            },
        )
        assert updated_response.status_code == 200
        updated = updated_response.get_json()
        assert updated['version'] == 2
        assert updated['parameters']['lr0'] == 0.00004
        assert updated['parameters']['epochs'] == 2

        cloned_response = self.client.post(
            f"/api/finetune-parameter-sets/{created['id']}/clone",
            json={},
        )
        assert cloned_response.status_code == 201
        cloned = cloned_response.get_json()
        assert cloned['id'] != created['id']
        assert cloned['name'].startswith('Two epoch smoke copy')
        assert cloned['version'] == 1

        archived_response = self.client.post(
            f"/api/finetune-parameter-sets/{created['id']}/archive",
            json={},
        )
        assert archived_response.status_code == 200
        assert archived_response.get_json()['is_active'] is False

        restored_response = self.client.post(
            f"/api/finetune-parameter-sets/{created['id']}/restore",
            json={},
        )
        assert restored_response.status_code == 200
        assert restored_response.get_json()['is_active'] is True

        deleted_response = self.client.delete(
            f"/api/finetune-parameter-sets/{cloned['id']}"
        )
        assert deleted_response.status_code == 200

        system_delete = self.client.delete(
            f"/api/finetune-parameter-sets/{seeded[0]['id']}"
        )
        assert system_delete.status_code == 409

    def test_parameter_set_snapshot_is_immutable_after_preset_edit(self):
        created_response = self.client.post(
            '/api/finetune-parameter-sets',
            json={
                'name': 'Immutable preset',
                'parameters': {
                    'epochs': 2,
                    'batch': 4,
                    'imgsz': 640,
                    'lr0': 0.00007,
                },
            },
        )
        assert created_response.status_code == 201
        created = created_response.get_json()
        parent_model_id = self.create_parent_model()

        with self.app.app_context():
            _batch, tasks = create_finetune_experiment({
                'project_id': self.project_ids[0],
                'parent_model_id': parent_model_id,
                'parameter_set_ids': [created['id']],
            })
            task_id = tasks[0].id
            original_request = dict(tasks[0].request_payload)
            original_snapshot = dict(tasks[0].parameter_set_snapshot)

        updated_response = self.client.patch(
            f"/api/finetune-parameter-sets/{created['id']}",
            json={'parameters': {'lr0': 0.00002, 'epochs': 3}},
        )
        assert updated_response.status_code == 200
        assert updated_response.get_json()['version'] == 2

        with self.app.app_context():
            task = db.session.get(TrainingQueueTask, task_id)
            assert task.request_payload == original_request
            assert task.parameter_set_snapshot == original_snapshot
            assert task.parameter_set_snapshot['version'] == 1
            assert task.parameter_set_snapshot['parameters']['lr0'] == 0.00007

        archived = self.client.post(
            f"/api/finetune-parameter-sets/{created['id']}/archive",
            json={},
        )
        assert archived.status_code == 200
        delete_used = self.client.delete(
            f"/api/finetune-parameter-sets/{created['id']}"
        )
        assert delete_used.status_code == 409

    def test_finetune_experiment_reuses_one_snapshot_and_hashes_candidates(self):
        parent_model_id = self.create_parent_model()
        parameter_set_ids = self.active_parameter_set_ids(5)
        with self.app.app_context():
            batch, tasks = create_finetune_experiment({
                'name': 'Phase 6 sweep',
                'project_id': self.project_ids[0],
                'parent_model_id': parent_model_id,
                'parameter_set_ids': parameter_set_ids,
            })
            assert batch.experiment_type == 'finetune_sweep'
            assert batch.parent_model_id == parent_model_id
            assert batch.training_dataset_id is not None
            assert len(tasks) == 5
            assert len({task.training_dataset_id for task in tasks}) == 1
            assert len({task.config_hash for task in tasks}) == 5
            assert all(task.parent_model_id == parent_model_id for task in tasks)
            assert all(
                task.request_payload['training_mode'] == 'finetune'
                for task in tasks
            )
            assert {
                task.parameter_set_id for task in tasks
            } == set(parameter_set_ids)
            assert all(task.parameter_set_snapshot for task in tasks)
            assert TrainingDataset.query.count() == 1

    def test_finetune_experiment_supports_two_candidate_smoke_test(self):
        parent_model_id = self.create_parent_model()
        config = self.client.get('/api/finetune/config').get_json()
        selected_parameter_sets = list(reversed([
            parameter_set
            for parameter_set in config['parameter_sets']
            if parameter_set['is_active']
        ][:2]))
        parameter_set_ids = [
            parameter_set['id']
            for parameter_set in selected_parameter_sets
        ]
        with self.app.app_context():
            batch, tasks = create_finetune_experiment({
                'name': 'Two candidate smoke test',
                'project_id': self.project_ids[0],
                'parent_model_id': parent_model_id,
                'parameter_set_ids': parameter_set_ids,
            })

            assert batch.total_jobs == 2
            assert len(tasks) == 2
            assert [task.candidate_name for task in tasks] == [
                f"{index}. {parameter_set['name']}"
                for index, parameter_set in enumerate(
                    selected_parameter_sets,
                    start=1,
                )
            ]
            assert [
                task.request_payload['lr0']
                for task in tasks
            ] == [
                parameter_set['parameters']['lr0']
                for parameter_set in selected_parameter_sets
            ]
            assert [
                task.parameter_set_snapshot['version']
                for task in tasks
            ] == [1, 1]
            assert len({task.training_dataset_id for task in tasks}) == 1
            assert TrainingDataset.query.count() == 1

    def test_two_workers_process_three_finetune_candidates_with_lineage(self):
        parent_model_id = self.create_parent_model()
        parameter_set_ids = self.active_parameter_set_ids(3)
        self.add_worker('FineTuneA')
        self.add_worker('FineTuneB')
        with self.app.app_context():
            batch, _tasks = create_finetune_experiment({
                'project_id': self.project_ids[0],
                'parent_model_id': parent_model_id,
                'parameter_set_ids': parameter_set_ids,
            })
            batch_id = batch.id

        state = FakeWorkerState()
        factory = lambda worker: FakeWorkerAdapter(worker, state)
        first = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert first['dispatched'] == 2
        second = dispatch_once(
            self.app,
            adapter_factory=factory,
            probe=False,
            asynchronous=False,
        )
        assert second['dispatched'] == 1

        with self.app.app_context():
            batch = db.session.get(TrainingBatch, batch_id)
            assert batch.status == 'succeeded'
            tasks = TrainingQueueTask.query.filter_by(
                batch_id=batch_id
            ).all()
            assert len(tasks) == 3
            assert all(
                task.metrics['metrics/mAP50-95(B)'] == 0.42
                for task in tasks
            )
            children = AIModel.query.filter_by(
                parent_model_id=parent_model_id,
                source_kind='training',
            ).all()
            assert len(children) == 3
            assert all(child.finetune_status == 'ready' for child in children)
            for child in children:
                artifact_kinds = {
                    artifact.kind for artifact in child.artifacts
                }
                assert {
                    'onnx',
                    'best_pt',
                    'last_pt',
                    'manifest',
                    'results',
                    'args',
                }.issubset(artifact_kinds)
        assert state.model_upload_count == 3

    def test_old_worker_does_not_receive_finetune_task(self):
        parent_model_id = self.create_parent_model()
        parameter_set_ids = self.active_parameter_set_ids(1)
        worker_id = self.add_worker('LegacyWorker')
        with self.app.app_context():
            worker = db.session.get(TrainingWorker, worker_id)
            worker.capabilities = {
                'training': True,
                'training_modes': ['fresh'],
                'model_artifact_upload': False,
                'max_concurrent_jobs': 1,
            }
            create_finetune_experiment({
                'project_id': self.project_ids[0],
                'parent_model_id': parent_model_id,
                'parameter_set_ids': parameter_set_ids,
            })
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
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'queued'

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

    def test_artifact_download_heartbeat_prevents_lease_expiry(self):
        self.add_worker('WorkerSlowArtifact')
        self.create_batch(project_ids=[self.project_ids[0]])
        self.app.config['TRAINING_TASK_HEARTBEAT_SECONDS'] = 0.05
        state = FakeWorkerState()
        download_started = threading.Event()
        allow_download = threading.Event()

        class SlowArtifactAdapter(FakeWorkerAdapter):
            def download_artifact(
                self,
                remote_job_id,
                artifact_kind,
                destination,
                progress_callback=None,
            ):
                download_started.set()
                if not allow_download.wait(timeout=3):
                    raise RuntimeError('test did not release artifact download')
                return super().download_artifact(
                    remote_job_id,
                    artifact_kind,
                    destination,
                    progress_callback=progress_callback,
                )

        result = dispatch_once(
            self.app,
            adapter_factory=lambda worker: SlowArtifactAdapter(worker, state),
            probe=False,
            asynchronous=True,
        )
        assert result['dispatched'] == 1
        assert download_started.wait(timeout=3)

        try:
            with self.app.app_context():
                task = TrainingQueueTask.query.one()
                task.lease_expires_at = utcnow() + timedelta(
                    milliseconds=100
                )
                db.session.commit()

            time.sleep(0.25)
            with self.app.app_context():
                assert recover_expired_leases() == 0
                task = TrainingQueueTask.query.one()
                assert task.status == 'downloading_artifacts'
                assert task.lease_expires_at > utcnow()
        finally:
            allow_download.set()

        self.wait_for_terminal_count(1)
        with self.app.app_context():
            assert TrainingQueueTask.query.one().status == 'succeeded'
            assert TrainingJobAttempt.query.one().status == 'succeeded'

    def test_parallel_artifact_downloads_use_isolated_partial_files(self):
        destination = self.artifact_root / 'parallel' / 'best.onnx'
        barrier = threading.Barrier(2)
        payloads = (b'fast-artifact', b'slow-artifact')
        response_index = 0
        response_lock = threading.Lock()

        class StreamingResponse:
            status_code = 200
            text = ''

            def __init__(self, payload, is_slow):
                self.payload = payload
                self.is_slow = is_slow
                self.headers = {
                    'Content-Length': str(len(payload)),
                }

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def iter_content(self, chunk_size):
                assert chunk_size == 1024 * 1024
                barrier.wait(timeout=3)
                if self.is_slow:
                    time.sleep(0.2)
                yield self.payload

        class StreamingSession:
            def get(self, *_args, **_kwargs):
                nonlocal response_index
                with response_lock:
                    index = response_index
                    response_index += 1
                return StreamingResponse(
                    payloads[index],
                    is_slow=index == 1,
                )

        adapter = ColabHttpWorkerAdapter(
            'https://parallel.trycloudflare.com',
            'test-token',
            session=StreamingSession(),
        )
        errors = []

        def download():
            try:
                adapter.download_artifact(
                    str(uuid.uuid4()),
                    'onnx',
                    destination,
                )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=download),
            threading.Thread(target=download),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert destination.read_bytes() in payloads
        assert list(destination.parent.glob('*.part')) == []

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
