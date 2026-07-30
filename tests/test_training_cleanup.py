import hashlib
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from artifact_object_store import ObjectStoreError
from models import (
    db,
    AIModel,
    ModelArtifact,
    Project,
    TrainingBatch,
    TrainingCheckpoint,
    TrainingDataset,
    TrainingJob,
    TrainingJobAttempt,
    TrainingJobEvent,
    TrainingQueueTask,
)
from test_helpers import create_isolated_test_app


class FakeCleanupObjectStore:
    backend_name = 's3'
    enabled = True

    def __init__(self):
        self.deleted = []

    def delete(self, object_key):
        self.deleted.append(object_key)


class TestTrainingCleanup:
    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='toolib_cleanup_')
        self.root = Path(self.temp_dir.name)
        self.dataset_root = self.root / 'datasets'
        self.artifact_root = self.root / 'training-artifacts'
        self.model_root = self.root / 'models'
        self.model_artifact_root = self.root / 'model-artifacts'
        self.app = create_isolated_test_app(
            str(self.root / 'cleanup.db'),
            TRAINING_DATASET_ROOT=str(self.dataset_root),
            TRAINING_ARTIFACT_ROOT=str(self.artifact_root),
            MODEL_STORAGE_ROOT=str(self.model_root),
            MODEL_ARTIFACT_ROOT=str(self.model_artifact_root),
        )
        self.client = self.app.test_client()
        self.object_store = FakeCleanupObjectStore()
        self.object_store_patch = mock.patch(
            'training_cleanup.checkpoint_store',
            return_value=self.object_store,
        )
        self.object_store_patch.start()

    def teardown_method(self):
        self.object_store_patch.stop()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def add_terminal_graph(self, *, imported_model=False):
        old = datetime.utcnow() - timedelta(days=60)
        dataset_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        remote_job_id = str(uuid.uuid4())
        dataset_path = self.dataset_root / dataset_id
        dataset_path.mkdir(parents=True)
        (dataset_path / 'dataset.zip').write_bytes(b'dataset-archive')
        task_path = self.artifact_root / task_id
        task_path.mkdir(parents=True)
        artifact_path = task_path / 'best.onnx'
        artifact_path.write_bytes(b'training-artifact')

        with self.app.app_context():
            project_root = self.root / 'project'
            project_root.mkdir(exist_ok=True)
            project = Project(name='Cleanup project', root_path=str(project_root))
            db.session.add(project)
            db.session.flush()
            dataset = TrainingDataset(
                dataset_id=dataset_id,
                project_id=project.id,
                status='uploaded',
                archive_path=str(dataset_path / 'dataset.zip'),
                archive_sha256='a' * 64,
                archive_size=15,
                storage_backend='s3',
                object_key=f'toolib/datasets/{dataset_id}/dataset.zip',
                created_at=old,
            )
            db.session.add(dataset)
            db.session.flush()
            batch = TrainingBatch(
                batch_id=str(uuid.uuid4()),
                name='Old completed batch',
                status='succeeded',
                training_dataset_id=dataset.id,
                total_jobs=1,
                succeeded_jobs=1,
                created_at=old,
                finished_at=old,
            )
            db.session.add(batch)
            db.session.flush()
            job = TrainingJob(
                remote_job_id=remote_job_id,
                project_id=project.id,
                training_dataset_id=dataset.id,
                dataset_id=dataset_id,
                remote_api_url='https://worker.example',
                status='succeeded',
                artifacts={
                    '_objects': {
                        'onnx': {
                            'object_key': f'toolib/artifacts/{task_id}/best.onnx',
                            'size_bytes': 17,
                        }
                    }
                },
                created_at=old,
                finished_at=old,
            )
            db.session.add(job)
            db.session.flush()
            task = TrainingQueueTask(
                task_id=task_id,
                idempotency_key=f'cleanup-{task_id}',
                batch_id=batch.id,
                project_id=project.id,
                training_dataset_id=dataset.id,
                training_job_id=job.id,
                status='succeeded',
                stage='completed',
                request_payload={'epochs': 10},
                dataset_config={},
                created_at=old,
                updated_at=old,
                finished_at=old,
            )
            db.session.add(task)
            db.session.flush()
            attempt = TrainingJobAttempt(
                attempt_id=str(uuid.uuid4()),
                task_id=task.id,
                training_job_id=job.id,
                attempt_number=1,
                status='succeeded',
                lease_token=str(uuid.uuid4()),
                started_at=old,
                finished_at=old,
            )
            db.session.add(attempt)
            db.session.flush()
            checkpoint = TrainingCheckpoint(
                checkpoint_id=str(uuid.uuid4()),
                task_id=task.id,
                attempt_id=attempt.id,
                generation=1,
                epoch=5,
                total_epochs=10,
                status='superseded',
                storage_backend='s3',
                object_key=f'toolib/training/{task_id}/checkpoint.pt',
                sha256='b' * 64,
                size_bytes=19,
                created_at=old,
            )
            db.session.add(checkpoint)
            db.session.add(TrainingJobEvent(
                task_id=task.id,
                attempt_id=attempt.id,
                event_type='completed',
                to_status='succeeded',
                created_at=old,
            ))

            model_id = None
            if imported_model:
                runtime_path = self.model_root / f'{task_id}.onnx'
                runtime_path.parent.mkdir(parents=True, exist_ok=True)
                runtime_path.write_bytes(b'runtime-model')
                model = AIModel(
                    name='Imported model',
                    filename=runtime_path.name,
                    source_kind='training',
                    training_dataset_id=dataset.id,
                )
                db.session.add(model)
                db.session.flush()
                db.session.add(ModelArtifact(
                    artifact_id=str(uuid.uuid4()),
                    model_id=model.id,
                    kind='onnx',
                    storage_path=str(artifact_path),
                    storage_backend='s3',
                    object_key=f'toolib/artifacts/{task_id}/best.onnx',
                    sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                    size_bytes=artifact_path.stat().st_size,
                    metadata_json={'task_id': task_id},
                ))
                task.imported_model_id = model.id
                job.imported_model_id = model.id
                model_id = model.id
            db.session.commit()
            return {
                'batch_id': batch.id,
                'dataset_id': dataset.id,
                'task_id': task.id,
                'job_id': job.id,
                'model_id': model_id,
                'dataset_path': dataset_path,
                'task_path': task_path,
            }

    def test_cleanup_dry_run_then_deletes_terminal_unreferenced_graph(self):
        graph = self.add_terminal_graph()

        preview = self.client.get(
            '/api/training-storage-cleanup?retention_days=30'
        )

        assert preview.status_code == 200
        plan = preview.get_json()
        assert plan['can_execute'] is True
        assert plan['summary']['batches'] == 1
        assert plan['summary']['tasks'] == 1
        assert plan['summary']['datasets'] == 1
        assert plan['summary']['database_rows'] == 7
        assert plan['summary']['local_paths'] == 2
        assert plan['summary']['object_keys'] == 3
        with self.app.app_context():
            assert TrainingBatch.query.count() == 1

        rejected = self.client.post(
            '/api/training-storage-cleanup',
            json={'retention_days': 30},
        )
        assert rejected.status_code == 400

        executed = self.client.post(
            '/api/training-storage-cleanup',
            json={'retention_days': 30, 'confirm': True},
        )

        assert executed.status_code == 200
        assert executed.get_json()['deleted']['database_rows'] == 7
        assert len(self.object_store.deleted) == 3
        assert not graph['dataset_path'].exists()
        assert not graph['task_path'].exists()
        with self.app.app_context():
            assert TrainingBatch.query.count() == 0
            assert TrainingQueueTask.query.count() == 0
            assert TrainingJob.query.count() == 0
            assert TrainingDataset.query.count() == 0
            assert TrainingJobAttempt.query.count() == 0
            assert TrainingJobEvent.query.count() == 0
            assert TrainingCheckpoint.query.count() == 0

    def test_cleanup_protects_graph_with_imported_model(self):
        graph = self.add_terminal_graph(imported_model=True)

        response = self.client.get(
            '/api/training-storage-cleanup?retention_days=30'
        )

        assert response.status_code == 200
        plan = response.get_json()
        assert plan['summary']['batches'] == 0
        assert plan['summary']['datasets'] == 0
        assert plan['protected']['batches']['imported_model'] == 1
        assert plan['protected']['datasets']['referenced'] == 1
        assert graph['dataset_path'].exists()
        assert graph['task_path'].exists()

    def test_dry_run_reports_object_store_configuration_error(self):
        self.add_terminal_graph()
        with mock.patch(
            'training_cleanup.checkpoint_store',
            side_effect=ObjectStoreError('broken object store'),
        ):
            response = self.client.get(
                '/api/training-storage-cleanup?retention_days=30'
            )

        assert response.status_code == 200
        plan = response.get_json()
        assert plan['can_execute'] is False
        assert plan['storage']['error'] == 'broken object store'

    def test_cleanup_protects_legacy_model_artifact_path_without_task_metadata(self):
        graph = self.add_terminal_graph()
        artifact_path = graph['task_path'] / 'best.onnx'
        with self.app.app_context():
            model = AIModel(
                name='Legacy imported model',
                filename='legacy-import.onnx',
                source_kind='training',
            )
            db.session.add(model)
            db.session.flush()
            db.session.add(ModelArtifact(
                artifact_id=str(uuid.uuid4()),
                model_id=model.id,
                kind='onnx',
                storage_path=str(artifact_path),
                sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                size_bytes=artifact_path.stat().st_size,
            ))
            db.session.commit()

        response = self.client.get(
            '/api/training-storage-cleanup?retention_days=30'
        )

        assert response.status_code == 200
        plan = response.get_json()
        assert plan['summary']['batches'] == 0
        assert plan['protected']['batches']['imported_model'] == 1
        assert graph['task_path'].exists()

    def test_delete_model_removes_runtime_local_artifact_and_r2_object(self):
        graph = self.add_terminal_graph(imported_model=True)
        with self.app.app_context():
            model = db.session.get(AIModel, graph['model_id'])
            runtime_path = self.model_root / model.filename
            artifact_path = Path(model.artifacts[0].storage_path)
            object_key = model.artifacts[0].object_key
            assert runtime_path.is_file()
            assert artifact_path.is_file()

        response = self.client.delete(f"/api/models/{graph['model_id']}")

        assert response.status_code == 200
        cleanup = response.get_json()['storage_cleanup']
        assert cleanup['object_keys'] == 1
        assert object_key in self.object_store.deleted
        assert not runtime_path.exists()
        assert not artifact_path.exists()
        with self.app.app_context():
            assert db.session.get(AIModel, graph['model_id']) is None
            task = db.session.get(TrainingQueueTask, graph['task_id'])
            assert task.imported_model_id is None


def test_colab_manager_exposes_training_storage_cleanup_controls():
    template = (
        Path(__file__).resolve().parents[1]
        / 'templates'
        / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    for marker in (
        'id="trainingStorageCleanupPanel"',
        'id="trainingCleanupRetentionDays"',
        'previewTrainingStorageCleanup()',
        'executeTrainingStorageCleanup()',
        'function renderTrainingStorageCleanup(plan)',
        '/api/training-storage-cleanup',
        'confirm: true',
    ):
        assert marker in template
