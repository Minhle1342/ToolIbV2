import os
import tempfile
from unittest.mock import patch

import pytest

from models import db
from test_helpers import assert_safe_test_database, create_isolated_test_app


@pytest.fixture
def isolated_app():
    with tempfile.TemporaryDirectory(prefix='toolib-export-api-') as temp_dir:
        database_path = os.path.join(temp_dir, 'test.db')
        app = create_isolated_test_app(database_path)
        with app.app_context():
            assert_safe_test_database(app, expected_root=temp_dir)
            try:
                yield app
            finally:
                db.session.remove()
                db.engine.dispose()


@pytest.fixture
def client(isolated_app):
    return isolated_app.test_client()


def test_export_api_normalizes_numeric_filters_before_querying(client, tmp_path):
    exported = {
        'status': 'success',
        'export_path': str(tmp_path),
    }
    with (
        patch('routes.utils.export_dataset', return_value=exported) as export_mock,
        patch('routes.run_clear_header_for_export', return_value=[]),
    ):
        response = client.post('/api/export', json={
            'project_ids': ['2'],
            'view_id': '3',
            'image_ids': ['4', 5],
            'tags': ['6'],
            'exclude_flagged': True,
            'has_any_tag': False,
            'include_untagged': 'false',
            'include_unlabeled': 'true',
            'splits': {'train': 80, 'val': 20, 'test': 0},
            'format': 'yolo',
        })

    assert response.status_code == 200
    export_mock.assert_called_once_with(
        {
            'project_ids': [2],
            'view_id': 3,
            'image_ids': [4, 5],
            'tags': [6],
            'exclude_flagged': True,
            'has_any_tag': False,
            'include_untagged': False,
            'include_unlabeled': True,
        },
        splits={'train': 80, 'val': 20, 'test': 0},
        format='yolo',
    )


@pytest.mark.parametrize(
    ('field_name', 'invalid_value'),
    (
        ('project_ids', ['not-an-integer']),
        ('view_id', 'not-an-integer'),
        ('image_ids', [True]),
        ('tags', 'not-a-list'),
        ('include_unlabeled', 'not-a-boolean'),
    ),
)
def test_export_api_rejects_invalid_filter_types(
    client,
    field_name,
    invalid_value,
):
    with patch('routes.utils.export_dataset') as export_mock:
        response = client.post('/api/export', json={field_name: invalid_value})

    assert response.status_code == 400
    assert response.get_json()['status'] == 'error'
    assert field_name in response.get_json()['message']
    export_mock.assert_not_called()
