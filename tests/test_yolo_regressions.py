import os
import tempfile
import pytest

import utils
from models import db, Project, Image, View
from test_helpers import create_isolated_test_app, assert_safe_test_database

@pytest.fixture
def isolated_app():
    with tempfile.TemporaryDirectory(prefix='toolib_test_') as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        app = create_isolated_test_app(db_path, FORCE_HTTPS_REDIRECTS=False)
        with app.app_context():
            assert_safe_test_database(app, expected_root=temp_dir)
            db.drop_all()
            db.create_all()
            # Pass the temp_dir so tests can create their dataset there
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

def test_update_project_same_normalized_root_preserves_images_and_views(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'update_project')
    os.makedirs(project_dir)

    with isolated_app.app_context():
        norm_dir = str(utils.find_dataset_root(project_dir))
        p = Project(name="Test Update", root_path=norm_dir)
        db.session.add(p)
        db.session.commit()

        v = View(name="View1", project_id=p.id)
        db.session.add(v)
        db.session.commit()

        img = Image(filename="a.jpg", project_id=p.id, view_id=v.id)
        db.session.add(img)
        db.session.commit()

        # Update with same path (denormalized slightly to ensure normalization logic kicks in)
        denorm_path = project_dir + os.sep
        resp = client.put(f'/api/projects/{p.id}', json={
            'name': 'Updated Name',
            'root_path': denorm_path
        })

        assert resp.status_code == 200

        # Verify images and views were not cleared
        assert Image.query.filter_by(project_id=p.id).count() == 1
        assert View.query.filter_by(project_id=p.id).count() == 1

        img_db = Image.query.filter_by(project_id=p.id).first()
        assert img_db.view_id == v.id

def test_get_images_reads_structured_labels(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'structured_ds')
    os.makedirs(os.path.join(project_dir, 'images', 'train'))
    os.makedirs(os.path.join(project_dir, 'labels', 'train'))

    with open(os.path.join(project_dir, 'images', 'train', 'a.jpg'), 'w') as f:
        f.write('dummy')

    # Write YOLO label: class_id 0, x=0.5, y=0.5, w=0.1, h=0.1
    with open(os.path.join(project_dir, 'labels', 'train', 'a.txt'), 'w') as f:
        f.write('0 0.5 0.5 0.1 0.1\n')

    with isolated_app.app_context():
        p = Project(name="Structured DS", root_path=project_dir)
        db.session.add(p)
        db.session.commit()

        # Manually scan
        utils.scan_and_sync_images(p)

        # Verify from GET API
        resp = client.get(f'/api/images?project_id={p.id}')
        assert resp.status_code == 200
        data = resp.json
        assert len(data) == 1

        # The API should return the boxes we wrote in a.txt
        img_data = data[0]
        assert 'boxes' in img_data
        assert len(img_data['boxes']) == 1
        box = img_data['boxes'][0]
        assert box['class_id'] == 0
        assert box['x_center'] == 0.5
        assert box['width'] == 0.1

        # Also ensure is_labeled got updated correctly
        db_img = Image.query.get(img_data['id'])
        assert db_img.is_labeled is True

def test_merge_preflight_structured_collision_has_no_false_missing_file(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']

    # Project 1
    p1_dir = os.path.join(temp_dir, 'ds1')
    os.makedirs(os.path.join(p1_dir, 'images', 'train'))
    with open(os.path.join(p1_dir, 'images', 'train', 'same.jpg'), 'w') as f:
        f.write('dummy1')

    # Project 2
    p2_dir = os.path.join(temp_dir, 'ds2')
    os.makedirs(os.path.join(p2_dir, 'images', 'val'))
    with open(os.path.join(p2_dir, 'images', 'val', 'same.jpg'), 'w') as f:
        f.write('dummy2')

    with isolated_app.app_context():
        p1 = Project(name="P1", root_path=p1_dir)
        p2 = Project(name="P2", root_path=p2_dir)
        db.session.add(p1)
        db.session.add(p2)
        db.session.commit()

        utils.scan_and_sync_images(p1)
        utils.scan_and_sync_images(p2)

        resp = client.post('/api/projects/merge/preflight', json={
            'project_ids': [p1.id, p2.id],
            'name': 'Merged',
            'root_path': os.path.join(temp_dir, 'merged'),
            'collision_policy': 'rename'
        })

        assert resp.status_code == 200, resp.json
        data = resp.json

        # Missing files should be empty, both files exist at their resolved paths
        assert data['missing_files'] == []

        # Since they have same basename 'same.jpg', there should be 1 duplicate group with 2 items
        groups = data['duplicate_groups']
        assert len(groups) == 1
        assert groups[0]['filename'] == 'same.jpg'
        assert len(groups[0]['occurrences']) == 2
