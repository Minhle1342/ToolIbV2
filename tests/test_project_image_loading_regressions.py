import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import event

from models import db, Image, Project, View
from test_helpers import create_isolated_test_app, assert_safe_test_database


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_app():
    with tempfile.TemporaryDirectory(prefix='toolib_test_') as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        app = create_isolated_test_app(
            db_path,
            FORCE_HTTPS_REDIRECTS=False,
        )
        with app.app_context():
            assert_safe_test_database(app, expected_root=temp_dir)
            db.drop_all()
            db.create_all()
            app.config['TEMP_DIR'] = temp_dir
            try:
                yield app
            finally:
                db.session.remove()
                db.drop_all()
                db.engine.dispose()


@pytest.fixture
def client(isolated_app):
    return isolated_app.test_client()


def test_get_images_binds_numeric_query_parameters_as_integers(
    isolated_app,
    client,
):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'query_parameter_types')
    os.makedirs(project_dir)

    with isolated_app.app_context():
        project = Project(name='Typed query parameters', root_path=project_dir)
        db.session.add(project)
        db.session.flush()

        view = View(name='Typed view', project_id=project.id)
        db.session.add(view)
        db.session.flush()

        image = Image(
            filename='missing.jpg',
            project_id=project.id,
            view_id=view.id,
        )
        db.session.add(image)
        db.session.commit()

        captured_parameters = []

        def capture_image_query(
            _connection,
            _cursor,
            statement,
            parameters,
            _context,
            _executemany,
        ):
            normalized_statement = ' '.join(statement.lower().split())
            if (
                'from images' in normalized_statement
                and 'images.project_id' in normalized_statement
                and 'images.view_id' in normalized_statement
            ):
                captured_parameters.append(parameters)

        event.listen(
            db.engine,
            'before_cursor_execute',
            capture_image_query,
        )
        try:
            response = client.get(
                f'/api/images?project_id={project.id}&view_id={view.id}'
            )
        finally:
            event.remove(
                db.engine,
                'before_cursor_execute',
                capture_image_query,
            )

        assert response.status_code == 200
        assert len(response.get_json()) == 1
        assert captured_parameters
        assert all(
            isinstance(value, int)
            for value in captured_parameters[0]
        )


@pytest.mark.parametrize(
    'query_string',
    (
        'project_id=not-a-number',
        'view_id=not-a-number',
    ),
)
def test_get_images_rejects_invalid_numeric_filters(client, query_string):
    response = client.get(f'/api/images?{query_string}')

    assert response.status_code == 400
    assert response.get_json() == {
        'error': 'project_id and view_id must be integers.'
    }


def test_workspace_replaces_loading_spinner_when_image_api_fails():
    api_source = (
        REPOSITORY_ROOT / 'static' / 'js' / 'api.js'
    ).read_text(encoding='utf-8')
    workspace_source = (
        REPOSITORY_ROOT / 'static' / 'js' / 'workspace.js'
    ).read_text(encoding='utf-8')

    assert 'if (!res.ok)' in api_source
    assert 'throw new Error(message);' in api_source
    assert 'Failed to load project images:' in workspace_source
    assert 'Không thể tải dữ liệu ảnh. Vui lòng thử lại.' in workspace_source
    assert 'onclick="loadImages(true)"' in workspace_source
