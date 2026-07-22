import os
import shutil
import pytest
from app import create_app, db
from models import Project, Image
from utils import scan_and_sync_images, resolve_image_path, resolve_label_path

@pytest.fixture
def app():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_yolo_import_and_resolution(app):
    test_dir = os.path.abspath('test_yolo_structure')
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    try:
        # Create YOLO structure
        os.makedirs(os.path.join(test_dir, 'images', 'train'))
        os.makedirs(os.path.join(test_dir, 'labels', 'train'))

        with open(os.path.join(test_dir, 'images', 'train', '1.jpg'), 'w') as f:
            f.write('dummy')
        with open(os.path.join(test_dir, 'labels', 'train', '1.txt'), 'w') as f:
            f.write('0 0.5 0.5 0.1 0.1\n')

        project = Project(name="Test YOLO", root_path=test_dir)
        db.session.add(project)
        db.session.commit()

        scan_and_sync_images(project)

        images = Image.query.filter_by(project_id=project.id).all()
        assert len(images) == 1
        img = images[0]

        # Identity
        assert img.filename.replace('\\', '/') == 'images/train/1.jpg'

        # Path resolution
        img_path = resolve_image_path(project.root_path, img.filename).replace('\\', '/')
        lbl_path = resolve_label_path(project.root_path, img.filename).replace('\\', '/')

        assert img_path.endswith('test_yolo_structure/images/train/1.jpg')
        assert lbl_path.endswith('test_yolo_structure/labels/train/1.txt')

    finally:
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

def test_legacy_flat_import(app):
    test_dir = os.path.abspath('test_legacy_flat')
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    try:
        os.makedirs(test_dir)

        with open(os.path.join(test_dir, '2.jpg'), 'w') as f:
            f.write('dummy')
        with open(os.path.join(test_dir, '2.txt'), 'w') as f:
            f.write('0 0.5 0.5 0.1 0.1\n')

        project = Project(name="Test Legacy", root_path=test_dir)
        db.session.add(project)
        db.session.commit()

        scan_and_sync_images(project)

        images = Image.query.filter_by(project_id=project.id).all()
        assert len(images) == 1
        img = images[0]

        # Identity
        assert img.filename == '2.jpg'

        # Path resolution
        img_path = resolve_image_path(project.root_path, img.filename).replace('\\', '/')
        lbl_path = resolve_label_path(project.root_path, img.filename).replace('\\', '/')

        assert img_path.endswith('test_legacy_flat/2.jpg')
        assert lbl_path.endswith('test_legacy_flat/2.txt')

    finally:
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
