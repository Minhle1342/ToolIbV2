import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest import mock

from models import AIModel, TrainingJob, db
from test_helpers import create_isolated_test_app


class ColabTrainingJobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='toolib_colab_jobs_test_')
        db_path = os.path.join(self.temp_dir.name, 'training_jobs.db')
        self.app = create_isolated_test_app(db_path)
        self.client = self.app.test_client()
        self.cwd_patch = mock.patch('routes.os.getcwd', return_value=self.temp_dir.name)
        self.cwd_patch.start()

    def tearDown(self):
        self.cwd_patch.stop()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def make_payload(self, **overrides):
        payload = {
            'remote_job_id': '30c6a110-0549-4b6b-aaae-66f21ec00df3',
            'remote_api_url': 'https://example.trycloudflare.com',
            'status': 'queued',
            'connection_status': 'synced',
            'current_epoch': 0,
            'total_epochs': 2,
            'message': 'Training job accepted.',
            'request': {
                'model': 'yolo11n.pt',
                'epochs': 2,
                'batch': 4,
                'imgsz': 640,
            },
            'created_at': '2026-07-27T02:45:00+00:00',
        }
        payload.update(overrides)
        return payload

    def sync_job(self, **overrides):
        return self.client.post(
            '/api/training-jobs/sync',
            json=self.make_payload(**overrides),
        )

    def test_sync_is_idempotent_and_does_not_persist_token_fields(self):
        payload = self.make_payload()
        payload['api_token'] = 'must-not-be-stored'
        payload['request']['token'] = 'must-not-be-stored'

        created = self.client.post('/api/training-jobs/sync', json=payload)
        self.assertEqual(created.status_code, 201)
        created_json = created.get_json()
        self.assertNotIn('api_token', created_json)
        self.assertNotIn('token', created_json['request'])

        updated = self.sync_job(
            status='running',
            current_epoch=1,
            message='Training epoch 1/2.',
        )
        self.assertEqual(updated.status_code, 200)
        updated_json = updated.get_json()
        self.assertEqual(created_json['id'], updated_json['id'])
        self.assertEqual('running', updated_json['status'])
        self.assertEqual(1, updated_json['current_epoch'])

        with self.app.app_context():
            self.assertEqual(1, TrainingJob.query.count())
            job = TrainingJob.query.one()
            self.assertNotIn('token', job.request_payload)

    def test_terminal_status_does_not_regress_to_running(self):
        succeeded = self.sync_job(
            status='succeeded',
            current_epoch=2,
            artifacts={'onnx': '/content/drive/MyDrive/ToolIb_PoC/artifacts/job/best.onnx'},
            finished_at='2026-07-27T02:50:00+00:00',
        )
        self.assertEqual(succeeded.status_code, 201)

        stale = self.sync_job(status='running', current_epoch=1)
        self.assertEqual(stale.status_code, 200)
        self.assertEqual('succeeded', stale.get_json()['status'])
        self.assertEqual(2, stale.get_json()['current_epoch'])

    def test_unreachable_connection_preserves_remote_status(self):
        created = self.sync_job(status='running')
        self.assertEqual(created.status_code, 201)

        unreachable = self.client.post(
            '/api/training-jobs/sync',
            json={
                'remote_job_id': self.make_payload()['remote_job_id'],
                'remote_api_url': 'https://example.trycloudflare.com',
                'connection_status': 'unreachable',
                'last_sync_error': 'Tunnel disconnected.',
            },
        )
        self.assertEqual(unreachable.status_code, 200)
        payload = unreachable.get_json()
        self.assertEqual('running', payload['status'])
        self.assertEqual('unreachable', payload['connection_status'])
        self.assertEqual('Tunnel disconnected.', payload['last_sync_error'])

    def test_sync_rejects_invalid_uuid_status_and_endpoint(self):
        invalid_uuid = self.sync_job(remote_job_id='not-a-uuid')
        self.assertEqual(invalid_uuid.status_code, 400)

        invalid_status = self.sync_job(status='unknown')
        self.assertEqual(invalid_status.status_code, 400)

        invalid_endpoint = self.sync_job(remote_api_url='http://public.example.com')
        self.assertEqual(invalid_endpoint.status_code, 400)

        endpoint_with_path = self.sync_job(
            remote_api_url='https://example.trycloudflare.com/api'
        )
        self.assertEqual(endpoint_with_path.status_code, 400)

    def test_succeeded_job_imports_inactive_model_and_links_history(self):
        succeeded = self.sync_job(
            status='succeeded',
            current_epoch=2,
            artifacts={'onnx': '/content/drive/MyDrive/ToolIb_PoC/artifacts/job/best.onnx'},
            finished_at='2026-07-27T02:50:00+00:00',
        )
        job_id = succeeded.get_json()['id']

        imported = self.client.post(
            '/api/models',
            data={
                'name': 'Colab yolo11n - 30c6a110',
                'description': 'Imported from test job',
                'model_type': 'detection',
                'training_job_id': str(job_id),
                'file': (io.BytesIO(b'fake-onnx-content'), 'yolo11n-30c6a110.onnx'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(imported.status_code, 201)
        imported_json = imported.get_json()
        self.assertFalse(imported_json['is_active'])
        self.assertFalse(imported_json['activation_ready'])

        listed = self.client.get('/api/models')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(1, len(listed.get_json()))
        self.assertFalse(listed.get_json()[0]['is_active'])

        with self.app.app_context():
            job = db.session.get(TrainingJob, job_id)
            model = db.session.get(AIModel, imported_json['id'])
            self.assertEqual(model.id, job.imported_model_id)
            self.assertFalse(model.is_active)
            self.assertFalse(model.activation_ready)

        duplicate = self.client.post(
            '/api/models',
            data={
                'name': 'Duplicate import',
                'model_type': 'detection',
                'training_job_id': str(job_id),
                'file': (io.BytesIO(b'fake-onnx-content'), 'duplicate.onnx'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(duplicate.status_code, 409)

        activated = self.client.post(f"/api/models/{imported_json['id']}/activate")
        self.assertEqual(activated.status_code, 200)
        self.assertTrue(activated.get_json()['is_active'])
        self.assertTrue(activated.get_json()['activation_ready'])

    def test_non_succeeded_job_cannot_import_model(self):
        queued = self.sync_job(status='queued')
        job_id = queued.get_json()['id']

        imported = self.client.post(
            '/api/models',
            data={
                'name': 'Too early',
                'model_type': 'detection',
                'training_job_id': str(job_id),
                'file': (io.BytesIO(b'fake-onnx-content'), 'too-early.onnx'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(imported.status_code, 409)

    def test_delete_history_keeps_imported_model_file_and_record(self):
        succeeded = self.sync_job(
            status='succeeded',
            artifacts={'onnx': '/content/drive/MyDrive/ToolIb_PoC/artifacts/job/best.onnx'},
        )
        job_id = succeeded.get_json()['id']
        imported = self.client.post(
            '/api/models',
            data={
                'name': 'Keep model',
                'model_type': 'detection',
                'training_job_id': str(job_id),
                'file': (io.BytesIO(b'fake-onnx-content'), 'keep-model.onnx'),
            },
            content_type='multipart/form-data',
        )
        model_id = imported.get_json()['id']

        deleted = self.client.delete(f'/api/training-jobs/{job_id}')
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(
            os.path.isfile(os.path.join(self.temp_dir.name, 'models', 'keep-model.onnx'))
        )
        with self.app.app_context():
            model = db.session.get(AIModel, model_id)
            self.assertIsNotNone(model)
            self.assertFalse(model.is_active)
            self.assertFalse(model.activation_ready)
            self.assertIsNone(db.session.get(TrainingJob, job_id))

        listed = self.client.get('/api/models')
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(listed.get_json()[0]['is_active'])

def test_existing_ai_models_table_receives_activation_ready_migration():
    with tempfile.TemporaryDirectory(prefix='toolib_colab_migration_test_') as temp_dir:
        db_path = os.path.join(temp_dir, 'legacy.db')
        with closing(sqlite3.connect(db_path)) as connection:
            with connection:
                connection.execute(
                    '''
                    CREATE TABLE ai_models (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        description VARCHAR(500),
                        filename VARCHAR(200) NOT NULL UNIQUE,
                        is_active BOOLEAN,
                        model_type VARCHAR(50),
                        created_at DATETIME
                    )
                    '''
                )

        app = create_isolated_test_app(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            columns = {
                row[1]: row
                for row in connection.execute('PRAGMA table_info(ai_models)').fetchall()
            }

        assert 'activation_ready' in columns
        assert columns['activation_ready'][3] == 1
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
