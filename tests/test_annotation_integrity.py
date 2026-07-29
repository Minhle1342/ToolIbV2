import os
import uuid
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import utils
from app import create_app
from models import db, Image, Project


REPO_ROOT = Path(__file__).resolve().parents[1]


def _postgres_schema_uri(base_uri, schema):
    url = make_url(base_uri)
    query = dict(url.query)
    query['options'] = f'-csearch_path={schema}'
    return url.set(query=query).render_as_string(hide_password=False)


@pytest.fixture(params=('sqlite', 'postgres'))
def annotation_app(request, tmp_path):
    admin_engine = None
    schema = None
    if request.param == 'postgres':
        postgres_uri = os.environ.get('TOOLIB_TEST_POSTGRES_URI')
        if not postgres_uri:
            pytest.skip('TOOLIB_TEST_POSTGRES_URI is not configured.')
        schema = f'toolib_annotation_test_{uuid.uuid4().hex}'
        admin_engine = create_engine(postgres_uri)
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        database_uri = _postgres_schema_uri(postgres_uri, schema)
    else:
        database_uri = f'sqlite:///{(tmp_path / "annotation.db").as_posix()}'

    app = create_app(config_overrides={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': database_uri,
        'FORCE_HTTPS_REDIRECTS': False,
    })
    app.config['ANNOTATION_TEST_ROOT'] = str(tmp_path / request.param)

    with app.app_context():
        if request.param == 'sqlite':
            db.drop_all()
            db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.engine.dispose()

    if admin_engine is not None:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def annotation_client(annotation_app):
    return annotation_app.test_client()


def _create_image(app, *, label_content=None, image_count=1):
    root = Path(app.config['ANNOTATION_TEST_ROOT'])
    image_dir = root / 'images' / 'train'
    image_dir.mkdir(parents=True, exist_ok=True)

    project = Project(name=f'Annotation {uuid.uuid4().hex}', root_path=str(root))
    db.session.add(project)
    db.session.flush()

    images = []
    for index in range(image_count):
        filename = f'images/train/image-{index}.jpg'
        (root / filename).write_bytes(b'image')
        image = Image(filename=filename, project_id=project.id)
        db.session.add(image)
        images.append(image)
    db.session.commit()

    label_path = Path(utils.resolve_label_path(project.root_path, images[0].filename))
    if label_content is not None:
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(label_content, encoding='utf-8')
        images[0].is_labeled = bool(label_content.strip())
        db.session.commit()
    return project, images, label_path


def _valid_label(class_id=0):
    return {
        'class_id': class_id,
        'x': 0.5,
        'y': 0.5,
        'w': 0.2,
        'h': 0.2,
    }


def test_assign_accepts_string_ids_on_sqlite_and_postgres(
    annotation_app,
    annotation_client,
):
    project, images, _label_path = _create_image(annotation_app, image_count=2)

    create_response = annotation_client.post('/api/views', json={
        'name': 'user1',
        'project_id': str(project.id),
    })
    assert create_response.status_code == 201, create_response.get_data(as_text=True)
    view_id = create_response.get_json()['id']

    assign_response = annotation_client.post('/api/views/assign', json={
        'view_id': str(view_id),
        'project_id': str(project.id),
        'count': '2',
        'assign_mode': 'unlabeled',
    })
    assert assign_response.status_code == 200, assign_response.get_data(as_text=True)
    db.session.expire_all()
    assert {db.session.get(Image, image.id).view_id for image in images} == {view_id}


def test_save_accepts_string_id_and_returns_new_revision(
    annotation_app,
    annotation_client,
):
    _project, images, label_path = _create_image(
        annotation_app,
        label_content='0 0.5 0.5 0.1 0.1\n',
    )
    image = images[0]
    state = annotation_client.get(
        f'/api/labels/{image.id}?include_revision=true'
    ).get_json()

    response = annotation_client.post('/api/save', json={
        'image_id': str(image.id),
        'labels': [_valid_label(1)],
        'is_reviewed': 'true',
        'expected_revision': state['revision'],
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['revision'] != state['revision']
    assert label_path.read_text(encoding='utf-8') == '1 0.5 0.5 0.2 0.2\n'
    db.session.expire_all()
    saved = db.session.get(Image, image.id)
    assert saved.is_labeled is True
    assert saved.is_reviewed is True


def test_stale_revision_returns_409_without_overwriting_file(
    annotation_app,
    annotation_client,
):
    _project, images, label_path = _create_image(
        annotation_app,
        label_content='0 0.5 0.5 0.1 0.1\n',
    )
    image = images[0]
    stale_revision = utils.label_file_revision(str(label_path))
    remote_content = '2 0.4 0.4 0.3 0.3\n'
    label_path.write_text(remote_content, encoding='utf-8')

    response = annotation_client.post('/api/save', json={
        'image_id': image.id,
        'labels': [_valid_label(1)],
        'expected_revision': stale_revision,
    })

    assert response.status_code == 409
    assert response.get_json()['conflict'] is True
    assert label_path.read_text(encoding='utf-8') == remote_content


def test_invalid_label_rejected_before_existing_file_is_touched(
    annotation_app,
    annotation_client,
):
    old_content = '0 0.5 0.5 0.1 0.1\n'
    _project, images, label_path = _create_image(
        annotation_app,
        label_content=old_content,
    )
    image = images[0]

    response = annotation_client.post('/api/save', json={
        'image_id': image.id,
        'labels': [{'class_id': 0, 'x': 0.5, 'y': 0.5, 'w': -1, 'h': 0.2}],
        'expected_revision': utils.label_file_revision(str(label_path)),
    })

    assert response.status_code == 400
    assert label_path.read_text(encoding='utf-8') == old_content


def test_database_failure_restores_previous_label_file(
    annotation_app,
    annotation_client,
):
    old_content = '0 0.5 0.5 0.1 0.1\n'
    _project, images, label_path = _create_image(
        annotation_app,
        label_content=old_content,
    )
    image = images[0]

    with mock.patch.object(
        db.session,
        'commit',
        side_effect=RuntimeError('forced commit failure'),
    ):
        response = annotation_client.post('/api/save', json={
            'image_id': image.id,
            'labels': [_valid_label(1)],
            'expected_revision': utils.label_file_revision(str(label_path)),
        })

    assert response.status_code == 500
    assert label_path.read_text(encoding='utf-8') == old_content
    db.session.expire_all()
    assert db.session.get(Image, image.id).is_labeled is True


def test_batch_review_normalizes_string_ids_and_boolean(
    annotation_app,
    annotation_client,
):
    _project, images, _label_path = _create_image(annotation_app, image_count=2)

    response = annotation_client.post('/api/images/batch-review', json={
        'image_ids': [str(image.id) for image in images],
        'is_reviewed': 'true',
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    db.session.expire_all()
    assert all(db.session.get(Image, image.id).is_reviewed for image in images)


def test_workspace_uses_server_revision_contract():
    api_source = (REPO_ROOT / 'static' / 'js' / 'api.js').read_text(encoding='utf-8')
    workspace_source = (
        REPO_ROOT / 'static' / 'js' / 'workspace.js'
    ).read_text(encoding='utf-8')

    assert 'async getLabelState(imageId)' in api_source
    assert 'expected_revision: currentImage.label_revision' in workspace_source
    assert 'error.status === 409' in workspace_source
