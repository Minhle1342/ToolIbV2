import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import yaml

import utils
from models import Image, Project, TrainingDataset, TrainingJob, db
from test_helpers import create_isolated_test_app


class FakeUploadResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class ColabTrainingDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix='toolib_colab_datasets_test_'
        )
        self.root = Path(self.temp_dir.name)
        db_path = self.root / 'training_datasets.db'
        self.snapshot_root = self.root / 'training_datasets'
        self.project_root = self.root / 'project'
        self.project_root.mkdir()
        (self.project_root / 'classes.txt').write_text(
            'bottle\ncap\n',
            encoding='utf-8',
        )

        self.app = create_isolated_test_app(str(db_path))
        self.client = self.app.test_client()
        with self.app.app_context():
            project = Project(name='Snapshot project', root_path=str(self.project_root))
            db.session.add(project)
            db.session.commit()
            self.project_id = project.id

        self.storage_patch = mock.patch(
            'routes.TRAINING_DATASET_ROOT',
            str(self.snapshot_root),
        )
        self.export_patch = mock.patch(
            'routes.utils.export_dataset',
            side_effect=self.fake_export_dataset,
        )
        self.clear_header_patch = mock.patch(
            'routes.run_clear_header_for_export',
            return_value=['train', 'val'],
        )
        self.storage_patch.start()
        self.export_mock = self.export_patch.start()
        self.clear_header_patch.start()

    def tearDown(self):
        self.clear_header_patch.stop()
        self.export_patch.stop()
        self.storage_patch.stop()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def fake_export_dataset(self, criteria, splits=None, format='yolo', output_dir=None):
        self.assertEqual({'project_ids': [self.project_id],
                          'include_unlabeled': False,
                          'exclude_flagged': True}, criteria)
        self.assertEqual({'train': 80, 'val': 20, 'test': 0}, splits)
        self.assertEqual('yolo', format)
        self.assertIsNotNone(output_dir)

        export_root = Path(output_dir).resolve()
        export_root.relative_to(self.snapshot_root.resolve())
        for split in ('train', 'val'):
            (export_root / 'images' / split).mkdir(parents=True, exist_ok=True)
            (export_root / 'labels' / split).mkdir(parents=True, exist_ok=True)

        for split, count in (('train', 4), ('val', 1)):
            for index in range(count):
                stem = f'{split}-{index}'
                (export_root / 'images' / split / f'{stem}.jpg').write_bytes(b'image')
                (export_root / 'labels' / split / f'{stem}.txt').write_text(
                    '0 0.5 0.5 0.2 0.2\n',
                    encoding='utf-8',
                )

        (export_root / 'data.yaml').write_text(
            yaml.safe_dump({
                'path': '.',
                'train': 'images/train',
                'val': 'images/val',
                'nc': 2,
                'names': ['bottle', 'cap'],
            }, sort_keys=False),
            encoding='utf-8',
        )
        return {
            'status': 'success',
            'export_path': str(export_root),
            'stats': {
                'total': 5,
                'unlabeled': 0,
                'train': 4,
                'val': 1,
                'test': 0,
            },
        }

    def prepare_snapshot(self):
        response = self.client.post(
            '/api/training-datasets',
            json={
                'project_id': self.project_id,
                'splits': {'train': 80, 'val': 20, 'test': 0},
                'include_unlabeled': False,
                'exclude_flagged': True,
            },
        )
        self.assertEqual(201, response.status_code, response.get_data(as_text=True))
        return response.get_json()

    def test_prepare_creates_job_scoped_archive_manifest_and_safe_response(self):
        global_export = self.root / 'exported_dataset'
        global_export.mkdir()
        sentinel = global_export / 'keep.txt'
        sentinel.write_text('untouched', encoding='utf-8')

        snapshot = self.prepare_snapshot()

        self.assertEqual('prepared', snapshot['status'])
        self.assertEqual(4, snapshot['train_count'])
        self.assertEqual(1, snapshot['val_count'])
        self.assertEqual(64, len(snapshot['archive_sha256']))
        self.assertNotIn('archive_path', snapshot)
        self.assertEqual('untouched', sentinel.read_text(encoding='utf-8'))

        snapshot_dir = self.snapshot_root / snapshot['dataset_id']
        self.assertTrue((snapshot_dir / 'dataset.zip').is_file())
        manifest = json.loads(
            (snapshot_dir / 'manifest.json').read_text(encoding='utf-8')
        )
        self.assertEqual(snapshot['dataset_id'], manifest['dataset_id'])
        self.assertTrue(
            (snapshot_dir / 'dataset' / 'toolib_manifest.json').is_file()
        )
        called_output_dir = Path(
            self.export_mock.call_args.kwargs['output_dir']
        ).resolve()
        self.assertEqual((snapshot_dir / 'dataset').resolve(), called_output_dir)

    def test_upload_streams_archive_and_never_persists_token(self):
        snapshot = self.prepare_snapshot()
        captured = {}

        def fake_post(url, **kwargs):
            captured['url'] = url
            captured['headers'] = kwargs['headers']
            captured['multipart_bytes'] = kwargs['data'].read()
            captured['has_files_argument'] = 'files' in kwargs
            return FakeUploadResponse({
                'status': 'uploaded',
                'dataset_id': snapshot['dataset_id'],
                'sha256': snapshot['archive_sha256'],
                'drive_path': (
                    '/content/drive/MyDrive/ToolIb_PoC/datasets/'
                    f"{snapshot['dataset_id']}/dataset.zip"
                ),
            })

        with mock.patch('routes.requests.post', side_effect=fake_post):
            uploaded = self.client.post(
                f"/api/training-datasets/{snapshot['id']}/upload",
                json={
                    'remote_api_url': 'https://phase4.trycloudflare.com',
                    'api_token': 'transient-secret-token',
                },
            )

        self.assertEqual(200, uploaded.status_code, uploaded.get_data(as_text=True))
        uploaded_json = uploaded.get_json()
        self.assertEqual('uploaded', uploaded_json['status'])
        self.assertEqual(
            'https://phase4.trycloudflare.com/api/datasets',
            captured['url'],
        )
        self.assertEqual(
            'Bearer transient-secret-token',
            captured['headers']['Authorization'],
        )
        self.assertTrue(
            captured['headers']['Content-Type'].startswith('multipart/form-data;')
        )
        self.assertFalse(captured['has_files_argument'])
        self.assertIn(snapshot['dataset_id'].encode(), captured['multipart_bytes'])
        self.assertIn(b'PK', captured['multipart_bytes'])

        with self.app.app_context():
            dataset = db.session.get(TrainingDataset, snapshot['id'])
            serialized = json.dumps(dataset.to_dict())
            self.assertNotIn('transient-secret-token', serialized)
            self.assertFalse(hasattr(dataset, 'api_token'))

    def test_upload_rejects_archive_modified_after_prepare(self):
        snapshot = self.prepare_snapshot()
        archive_path = self.snapshot_root / snapshot['dataset_id'] / 'dataset.zip'
        with archive_path.open('ab') as stream:
            stream.write(b'tampered')

        with mock.patch('routes.requests.post') as remote_post:
            response = self.client.post(
                f"/api/training-datasets/{snapshot['id']}/upload",
                json={
                    'remote_api_url': 'https://phase4.trycloudflare.com',
                    'api_token': 'transient-secret-token',
                },
            )

        self.assertEqual(400, response.status_code)
        self.assertIn('checksum has changed', response.get_json()['error'])
        remote_post.assert_not_called()

    def test_training_job_sync_links_dataset_and_project(self):
        snapshot = self.prepare_snapshot()
        remote_job_id = '96d49f32-eef4-4d50-b461-ffbde02bbb3f'
        response = self.client.post(
            '/api/training-jobs/sync',
            json={
                'remote_job_id': remote_job_id,
                'remote_api_url': 'https://phase4.trycloudflare.com',
                'status': 'queued',
                'request': {
                    'model': 'yolo11n.pt',
                    'epochs': 2,
                    'batch': 4,
                    'imgsz': 640,
                    'dataset_id': snapshot['dataset_id'],
                    'api_token': 'must-not-be-stored',
                },
            },
        )

        self.assertEqual(201, response.status_code, response.get_data(as_text=True))
        job_json = response.get_json()
        self.assertEqual(snapshot['dataset_id'], job_json['dataset_id'])
        self.assertEqual(snapshot['id'], job_json['training_dataset_id'])
        self.assertEqual(self.project_id, job_json['project_id'])
        self.assertNotIn('api_token', job_json['request'])

        with self.app.app_context():
            job = TrainingJob.query.filter_by(remote_job_id=remote_job_id).one()
            self.assertEqual(snapshot['id'], job.training_dataset_id)
            self.assertEqual(self.project_id, job.project_id)

    def test_prepare_rejects_invalid_phase4_split(self):
        response = self.client.post(
            '/api/training-datasets',
            json={
                'project_id': self.project_id,
                'splits': {'train': 100, 'val': 0, 'test': 0},
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertIn('non-zero train and val', response.get_json()['error'])
        self.export_mock.assert_not_called()


def test_legacy_training_jobs_table_receives_phase4_columns_and_dataset_table():
    with tempfile.TemporaryDirectory(
        prefix='toolib_colab_dataset_migration_test_'
    ) as temp_dir:
        db_path = os.path.join(temp_dir, 'legacy.db')
        with closing(sqlite3.connect(db_path)) as connection:
            with connection:
                connection.execute(
                    '''
                    CREATE TABLE training_jobs (
                        id INTEGER PRIMARY KEY,
                        remote_job_id VARCHAR(36) NOT NULL UNIQUE
                    )
                    '''
                )

        app = create_isolated_test_app(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            training_job_columns = {
                row[1]
                for row in connection.execute(
                    'PRAGMA table_info(training_jobs)'
                ).fetchall()
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

        assert 'training_dataset_id' in training_job_columns
        assert 'dataset_id' in training_job_columns
        assert 'training_datasets' in tables
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_export_dataset_supports_custom_snapshot_directory_without_global_output():
    with tempfile.TemporaryDirectory(
        prefix='toolib_colab_custom_export_test_'
    ) as temp_dir:
        root = Path(temp_dir)
        db_path = root / 'custom_export.db'
        project_root = root / 'project'
        images_root = project_root / 'images'
        labels_root = project_root / 'labels'
        images_root.mkdir(parents=True)
        labels_root.mkdir(parents=True)
        (project_root / 'classes.txt').write_text('bottle\n', encoding='utf-8')

        app = create_isolated_test_app(str(db_path))
        with app.app_context():
            project = Project(name='Custom export', root_path=str(project_root))
            db.session.add(project)
            db.session.commit()
            for index in range(5):
                relative_image = f'images/image-{index}.jpg'
                (project_root / relative_image).write_bytes(b'image')
                (labels_root / f'image-{index}.txt').write_text(
                    '0 0.5 0.5 0.2 0.2\n',
                    encoding='utf-8',
                )
                db.session.add(Image(
                    filename=relative_image,
                    project_id=project.id,
                    is_labeled=True,
                ))
            db.session.commit()

            global_export = root / 'exported_dataset'
            global_export.mkdir()
            sentinel = global_export / 'keep.txt'
            sentinel.write_text('untouched', encoding='utf-8')
            custom_output = root / 'snapshots' / 'dataset-id' / 'dataset'

            result = utils.export_dataset(
                {'project_ids': [project.id]},
                splits={'train': 80, 'val': 20, 'test': 0},
                format='yolo',
                output_dir=str(custom_output),
            )

            assert result['status'] == 'success'
            assert Path(result['export_path']) == custom_output.resolve()
            assert result['stats']['train'] == 4
            assert result['stats']['val'] == 1
            assert (custom_output / 'data.yaml').is_file()
            assert sentinel.read_text(encoding='utf-8') == 'untouched'
            db.session.remove()
            db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
