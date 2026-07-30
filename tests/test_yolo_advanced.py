import os
import tempfile
import pytest
import shutil
import json

import utils
from models import db, Project, Image, Tag, View
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

def test_create_project_normalizes_root_path_and_finds_labels(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    dataset_dir = os.path.join(temp_dir, 'my_dataset')
    img_dir = os.path.join(dataset_dir, 'images', 'train')
    lbl_dir = os.path.join(dataset_dir, 'labels', 'train')
    os.makedirs(img_dir)
    os.makedirs(lbl_dir)

    with open(os.path.join(dataset_dir, 'data.yaml'), 'w') as f:
        f.write('names: [class0]')

    with open(os.path.join(img_dir, 'a.jpg'), 'w') as f:
        f.write('dummy')
    with open(os.path.join(lbl_dir, 'a.txt'), 'w') as f:
        f.write('0 0.5 0.5 0.1 0.1')

    # Post with subfolder path
    resp = client.post('/api/projects', json={
        'name': 'My Proj',
        'root_path': img_dir
    })
    assert resp.status_code == 201

    with isolated_app.app_context():
        p = Project.query.filter_by(name='My Proj').first()
        # root_path should be dataset_dir
        assert p.root_path == dataset_dir

        img = Image.query.filter_by(project_id=p.id).first()
        # filename should be relative to dataset_dir
        assert img.filename == 'images/train/a.jpg'
        assert img.is_labeled is True

def test_save_label_structured_auto_creates_dir(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_save_label')
    img_dir = os.path.join(project_dir, 'images', 'train')
    os.makedirs(img_dir)
    with open(os.path.join(img_dir, 'a.jpg'), 'w') as f:
        f.write('dummy')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)

        img = Image.query.filter_by(project_id=p.id).first()

        # Save label via API
        resp = client.post('/api/save', json={
            'image_id': img.id,
            'labels': [{'class_id': 1, 'x': 0.5, 'y': 0.5, 'w': 0.1, 'h': 0.1}]
        })
        assert resp.status_code == 200

        # Verify labels/train/a.txt was created
        label_file = os.path.join(project_dir, 'labels', 'train', 'a.txt')
        assert os.path.exists(label_file)
        with open(label_file, 'r') as f:
            content = f.read()
            assert '1 0.5 0.5 0.1 0.1' in content

def test_read_yolo_label_structured(isolated_app):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_read_label')
    os.makedirs(os.path.join(project_dir, 'images', 'train'))
    os.makedirs(os.path.join(project_dir, 'labels', 'train'))

    with open(os.path.join(project_dir, 'images', 'train', 'a.jpg'), 'w') as f:
        f.write('dummy')
    with open(os.path.join(project_dir, 'labels', 'train', 'a.txt'), 'w') as f:
        f.write('2 0.4 0.4 0.2 0.2\n')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)

        img = Image.query.filter_by(project_id=p.id).first()
        labels = utils.read_yolo_label(img)
        assert len(labels) == 1
        assert labels[0]['class_id'] == 2

def test_delete_image_structured(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_del')
    os.makedirs(os.path.join(project_dir, 'images', 'train'))
    os.makedirs(os.path.join(project_dir, 'labels', 'train'))

    img_path = os.path.join(project_dir, 'images', 'train', 'a.jpg')
    lbl_path = os.path.join(project_dir, 'labels', 'train', 'a.txt')

    with open(img_path, 'w') as f:
        f.write('dummy')
    with open(lbl_path, 'w') as f:
        f.write('0 0.5 0.5 0.1 0.1')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)

        img = Image.query.filter_by(project_id=p.id).first()
        resp = client.delete(f'/api/images/{img.id}')
        assert resp.status_code == 200

        # Verify files are deleted
        assert not os.path.exists(img_path)
        assert not os.path.exists(lbl_path)

def test_export_dataset_structured(isolated_app):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_export')
    os.makedirs(os.path.join(project_dir, 'images', 'train'))
    os.makedirs(os.path.join(project_dir, 'labels', 'train'))

    with open(os.path.join(project_dir, 'images', 'train', 'a.jpg'), 'w') as f:
        f.write('dummy')
    with open(os.path.join(project_dir, 'labels', 'train', 'a.txt'), 'w') as f:
        f.write('0 0.5 0.5 0.1 0.1')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)

        img = Image.query.filter_by(project_id=p.id).first()
        img.is_labeled = True # Need for export
        db.session.commit()

        res = utils.export_dataset({'project_ids': [p.id], 'include_unlabeled': True}, splits={'train': 100}, format='yolo')

        # Check exported tree
        exp_dir = os.path.abspath("exported_dataset")
        # Should be flat destination: export_filename = f"{img.project_id}_{img.id}_a.jpg"
        exp_img_name = f"{p.id}_{img.id}_a.jpg"
        exp_lbl_name = f"{p.id}_{img.id}_a.txt"

        assert os.path.exists(os.path.join(exp_dir, 'images', 'train', exp_img_name))
        assert os.path.exists(os.path.join(exp_dir, 'labels', 'train', exp_lbl_name))

def test_class_operations_structured(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_class')
    os.makedirs(os.path.join(project_dir, 'images', 'val'))
    os.makedirs(os.path.join(project_dir, 'labels', 'val'))

    with open(os.path.join(project_dir, 'images', 'val', 'a.jpg'), 'w') as f:
        f.write('dummy')
    with open(os.path.join(project_dir, 'labels', 'val', 'a.txt'), 'w') as f:
        # class 0 and class 1
        f.write('0 0.5 0.5 0.1 0.1\n1 0.4 0.4 0.2 0.2\n')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)
        utils.save_classes(p, ['Class 0', 'Class 1'])

        # Delete class 0
        resp = client.delete(f'/api/projects/{p.id}/classes/0')
        assert resp.status_code == 200

        # Check label updated
        with open(os.path.join(project_dir, 'labels', 'val', 'a.txt'), 'r') as f:
            content = f.read()
            # Old class 1 should become class 0
            assert '0 0.4 0.4 0.2 0.2' in content

def test_merge_execute_structured(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']

    # Project 1
    p1_dir = os.path.join(temp_dir, 'ds1')
    os.makedirs(os.path.join(p1_dir, 'images', 'train'))
    os.makedirs(os.path.join(p1_dir, 'labels', 'train'))
    with open(os.path.join(p1_dir, 'images', 'train', 'same.jpg'), 'w') as f:
        f.write('dummy1')
    with open(os.path.join(p1_dir, 'labels', 'train', 'same.txt'), 'w') as f:
        f.write('0 0.5 0.5 0.1 0.1')

    # Project 2
    p2_dir = os.path.join(temp_dir, 'ds2')
    os.makedirs(os.path.join(p2_dir, 'images', 'val'))
    os.makedirs(os.path.join(p2_dir, 'labels', 'val'))
    with open(os.path.join(p2_dir, 'images', 'val', 'same.jpg'), 'w') as f:
        f.write('dummy2')
    with open(os.path.join(p2_dir, 'labels', 'val', 'same.txt'), 'w') as f:
        f.write('1 0.5 0.5 0.1 0.1')

    merged_dir = os.path.join(temp_dir, 'merged')

    with isolated_app.app_context():
        p1 = Project(name="P1", root_path=p1_dir)
        p2 = Project(name="P2", root_path=p2_dir)
        db.session.add(p1)
        db.session.add(p2)
        db.session.commit()
        utils.scan_and_sync_images(p1)
        utils.scan_and_sync_images(p2)
        img1 = Image.query.filter_by(project_id=p1.id).first()
        img2 = Image.query.filter_by(project_id=p2.id).first()

        # Call preflight
        client.post('/api/projects/merge/preflight', json={
            'project_ids': [p1.id, p2.id],
            'name': 'Merged',
            'root_path': merged_dir,
            'collision_policy': 'rename'
        })

        # Execute merge
        resp = client.post('/api/projects/merge', json={
            'project_ids': [p1.id, p2.id],
            'name': 'Merged',
            'root_path': merged_dir,
            'collision_policy': 'rename'
        })
        assert resp.status_code == 200

        # Check dest flat
        import pathlib
        dest_fn1 = f"{p1.id}_{img1.id}_same.jpg"
        dest_txt1 = f"{p1.id}_{img1.id}_same.txt"
        dest_fn2 = f"{p2.id}_{img2.id}_same.jpg"
        dest_txt2 = f"{p2.id}_{img2.id}_same.txt"
        assert os.path.exists(os.path.join(merged_dir, dest_fn1))
        assert os.path.exists(os.path.join(merged_dir, dest_txt1))
        assert os.path.exists(os.path.join(merged_dir, dest_fn2))
        assert os.path.exists(os.path.join(merged_dir, dest_txt2))

def test_merge_uses_exact_destination_path_not_dataset_ancestor(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']

    # 1. Create ancestor folder with data.yaml
    parent_dataset = os.path.join(temp_dir, 'parent_dataset')
    os.makedirs(parent_dataset)
    with open(os.path.join(parent_dataset, 'data.yaml'), 'w') as f:
        f.write('names: [class1]')

    merge_dest = os.path.join(parent_dataset, 'outputs', 'intended_merge_destination')

    # 2. Create source projects
    p1_dir = os.path.join(temp_dir, 'ds1')
    os.makedirs(os.path.join(p1_dir, 'images', 'train'))
    with open(os.path.join(p1_dir, 'images', 'train', 'a.jpg'), 'w') as f:
        f.write('dummy')

    p2_dir = os.path.join(temp_dir, 'ds2')
    os.makedirs(os.path.join(p2_dir, 'images', 'val'))
    with open(os.path.join(p2_dir, 'images', 'val', 'b.jpg'), 'w') as f:
        f.write('dummy2')

    with isolated_app.app_context():
        p1 = Project(name="P1", root_path=p1_dir)
        p2 = Project(name="P2", root_path=p2_dir)
        db.session.add(p1)
        db.session.add(p2)
        db.session.commit()
        utils.scan_and_sync_images(p1)
        utils.scan_and_sync_images(p2)
        img1 = Image.query.filter_by(project_id=p1.id).first()
        img2 = Image.query.filter_by(project_id=p2.id).first()

        # 3. POST merge
        resp = client.post('/api/projects/merge', json={
            'project_ids': [p1.id, p2.id],
            'name': 'Merged',
            'root_path': merge_dest,
            'collision_policy': 'rename'
        })
        assert resp.status_code == 200

        # 4. Assert response and filesystem
        # File should be in merge_dest, NOT in parent_dataset
        import pathlib
        dest_fn1 = f"{p1.id}_{img1.id}_a.jpg"
        dest_fn2 = f"{p2.id}_{img2.id}_b.jpg"

        assert os.path.exists(os.path.join(merge_dest, dest_fn1))
        assert os.path.exists(os.path.join(merge_dest, dest_fn2))
        assert not os.path.exists(os.path.join(parent_dataset, dest_fn1))


def test_merge_single_project_preserves_metadata_and_persists_tags(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    source_dir = os.path.join(temp_dir, 'single_source')
    os.makedirs(os.path.join(source_dir, 'images', 'train'))
    os.makedirs(os.path.join(source_dir, 'labels', 'train'))
    with open(os.path.join(source_dir, 'images', 'train', 'sample.jpg'), 'w') as f:
        f.write('image')
    with open(os.path.join(source_dir, 'labels', 'train', 'sample.txt'), 'w') as f:
        f.write('0 0.5 0.5 0.2 0.2\n')

    destination = os.path.join(temp_dir, 'single_copy')

    with isolated_app.app_context():
        source = Project(name='Single Source', root_path=source_dir)
        db.session.add(source)
        db.session.commit()
        utils.save_classes(source, ['bottle'])
        utils.scan_and_sync_images(source)

        image = Image.query.filter_by(project_id=source.id).one()
        tag = Tag(name='approved', color='#22c55e', project_id=source.id)
        db.session.add(tag)
        image.tags.append(tag)
        image.is_reviewed = True
        image.flag_status = 'Review'
        image.split_type = 'val'
        db.session.commit()

        response = client.post('/api/projects/merge', json={
            'project_ids': [source.id],
            'name': 'Single Copy',
            'root_path': destination,
            'collision_policy': 'rename',
        })

        assert response.status_code == 200, response.json
        assert response.json['copied_images'] == 1
        copied_project = Project.query.get(response.json['project']['id'])
        copied_image = Image.query.filter_by(project_id=copied_project.id).one()
        assert copied_image.is_reviewed is True
        assert copied_image.flag_status == 'Review'
        assert copied_image.split_type == 'val'
        assert [item.name for item in copied_image.tags] == ['approved']

        tags_path = os.path.join(destination, 'dataset_tags.json')
        assert os.path.exists(tags_path)
        with open(tags_path, 'r', encoding='utf-8') as f:
            tags_payload = json.load(f)
        assert tags_payload['project_tags'] == [
            {'id': copied_image.tags[0].id, 'name': 'approved', 'color': '#22c55e'}
        ]
        assert tags_payload['images'][copied_image.filename] == ['approved']


def test_merge_sources_support_per_project_tag_filters(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']

    def create_source(name, image_names, class_name):
        root = os.path.join(temp_dir, name)
        os.makedirs(os.path.join(root, 'images', 'train'))
        os.makedirs(os.path.join(root, 'labels', 'train'))
        for image_name in image_names:
            with open(os.path.join(root, 'images', 'train', image_name), 'w') as f:
                f.write(image_name)
            label_name = os.path.splitext(image_name)[0] + '.txt'
            with open(os.path.join(root, 'labels', 'train', label_name), 'w') as f:
                f.write('0 0.5 0.5 0.2 0.2\n')

        project = Project(name=name, root_path=root)
        db.session.add(project)
        db.session.commit()
        utils.save_classes(project, [class_name])
        utils.scan_and_sync_images(project)
        return project

    with isolated_app.app_context():
        project_a = create_source('project_a', ['keep_a.jpg', 'drop_a.jpg'], 'class_a')
        project_b = create_source('project_b', ['keep_b.jpg', 'drop_b.jpg'], 'class_b')

        tag_a = Tag(name='selected-a', project_id=project_a.id)
        tag_b = Tag(name='selected-b', project_id=project_b.id)
        db.session.add_all([tag_a, tag_b])
        db.session.flush()
        keep_a = Image.query.filter_by(
            project_id=project_a.id,
            filename='images/train/keep_a.jpg',
        ).one()
        keep_b = Image.query.filter_by(
            project_id=project_b.id,
            filename='images/train/keep_b.jpg',
        ).one()
        keep_a.tags.append(tag_a)
        keep_b.tags.append(tag_b)
        db.session.commit()

        destination = os.path.join(temp_dir, 'tag_filtered_merge')
        payload = {
            'sources': [
                {
                    'project_id': project_a.id,
                    'selection': {'mode': 'tags', 'tag_ids': [tag_a.id], 'match': 'any'},
                },
                {
                    'project_id': project_b.id,
                    'selection': {'mode': 'tags', 'tag_ids': [tag_b.id], 'match': 'any'},
                },
            ],
            'name': 'Tag Filtered Merge',
            'root_path': destination,
            'collision_policy': 'rename',
        }

        preflight = client.post('/api/projects/merge/preflight', json=payload)
        assert preflight.status_code == 200, preflight.json
        assert preflight.json['total_images'] == 2
        assert [item['matched_image_count'] for item in preflight.json['source_summaries']] == [1, 1]
        assert preflight.json['can_merge'] is True

        mixed_preflight = client.post('/api/projects/merge/preflight', json={
            **payload,
            'root_path': os.path.join(temp_dir, 'mixed_merge'),
            'sources': [
                payload['sources'][0],
                {
                    'project_id': project_b.id,
                    'selection': {'mode': 'all'},
                },
            ],
        })
        assert mixed_preflight.status_code == 200, mixed_preflight.json
        assert mixed_preflight.json['total_images'] == 3
        assert [
            item['matched_image_count']
            for item in mixed_preflight.json['source_summaries']
        ] == [1, 2]

        response = client.post('/api/projects/merge', json=payload)
        assert response.status_code == 200, response.json
        merged_project_id = response.json['project']['id']
        merged_images = Image.query.filter_by(project_id=merged_project_id).order_by(Image.id).all()
        assert len(merged_images) == 2
        assert {os.path.basename(image.filename) for image in merged_images} == {
            f'{project_a.id}_{keep_a.id}_keep_a.jpg',
            f'{project_b.id}_{keep_b.id}_keep_b.jpg',
        }
        assert {tag.name for image in merged_images for tag in image.tags} == {
            'selected-a',
            'selected-b',
        }
        assert response.json['merged_classes'] == ['class_a', 'class_b']


def test_merge_rejects_tag_from_another_project(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    with isolated_app.app_context():
        project_a = Project(name='A', root_path=os.path.join(temp_dir, 'a'))
        project_b = Project(name='B', root_path=os.path.join(temp_dir, 'b'))
        os.makedirs(project_a.root_path)
        os.makedirs(project_b.root_path)
        db.session.add_all([project_a, project_b])
        db.session.commit()
        foreign_tag = Tag(name='foreign', project_id=project_b.id)
        db.session.add(foreign_tag)
        db.session.commit()

        response = client.post('/api/projects/merge/preflight', json={
            'sources': [{
                'project_id': project_a.id,
                'selection': {'mode': 'tags', 'tag_ids': [foreign_tag.id]},
            }],
            'name': 'Invalid',
            'root_path': os.path.join(temp_dir, 'invalid'),
            'collision_policy': 'rename',
        })

        assert response.status_code == 400
        assert 'do not belong to project' in response.json['error']


def test_bulk_assign_tags_updates_only_selected_project_images(isolated_app, client):
    temp_dir = isolated_app.config['TEMP_DIR']
    with isolated_app.app_context():
        project = Project(name='Bulk Tags', root_path=os.path.join(temp_dir, 'bulk_tags'))
        other_project = Project(name='Other', root_path=os.path.join(temp_dir, 'other'))
        db.session.add_all([project, other_project])
        db.session.flush()

        selected = Image(filename='selected.jpg', project_id=project.id)
        untouched = Image(filename='untouched.jpg', project_id=project.id)
        foreign = Image(filename='foreign.jpg', project_id=other_project.id)
        tag = Tag(name='review', project_id=project.id)
        db.session.add_all([selected, untouched, foreign, tag])
        db.session.commit()

        response = client.post(f'/api/projects/{project.id}/bulk_assign_tags', json={
            'image_ids': [selected.id, foreign.id],
            'tag_ids': [tag.id],
            'action': 'assign',
        })
        assert response.status_code == 200, response.get_json()
        assert response.get_json()['success'] is True

        db.session.expire_all()
        assert [item.id for item in db.session.get(Image, selected.id).tags] == [tag.id]
        assert db.session.get(Image, untouched.id).tags == []
        assert db.session.get(Image, foreign.id).tags == []

        response = client.post(f'/api/projects/{project.id}/bulk_assign_tags', json={
            'image_ids': [selected.id],
            'tag_ids': [tag.id],
            'action': 'unassign',
        })
        assert response.status_code == 200, response.get_json()
        db.session.expire_all()
        assert db.session.get(Image, selected.id).tags == []


def test_data_yaml_classes_txt(isolated_app):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_yaml')
    os.makedirs(project_dir)

    yaml_content = """
names:
  0: cat
  1: dog
"""
    with open(os.path.join(project_dir, 'data.yaml'), 'w') as f:
        f.write(yaml_content)

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)

        classes_file = os.path.join(project_dir, 'classes.txt')
        assert os.path.exists(classes_file)
        with open(classes_file, 'r') as f:
            classes = [c.strip() for c in f.readlines()]
            assert classes == ['cat', 'dog']

def test_get_classes_structured_without_yaml_or_classes_file(isolated_app):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_get_classes')
    os.makedirs(os.path.join(project_dir, 'images', 'train'))
    os.makedirs(os.path.join(project_dir, 'labels', 'train'))

    with open(os.path.join(project_dir, 'images', 'train', 'a.jpg'), 'w') as f:
        f.write('dummy')
    # Use class_id = 3
    with open(os.path.join(project_dir, 'labels', 'train', 'a.txt'), 'w') as f:
        f.write('3 0.5 0.5 0.1 0.1\n')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()
        utils.scan_and_sync_images(p)

        # Scan should have created classes.txt automatically via get_classes if not found
        # But wait, we want to call get_classes explicitly when classes.txt DOES NOT exist
        classes_file = os.path.join(project_dir, 'classes.txt')
        if os.path.exists(classes_file):
            os.remove(classes_file)

        classes = utils.get_classes(p)
        assert len(classes) == 4 # Max class is 3, so [0, 1, 2, 3]

def test_partial_migration_metadata_preservation(isolated_app):
    temp_dir = isolated_app.config['TEMP_DIR']
    project_dir = os.path.join(temp_dir, 'proj_partial')
    os.makedirs(os.path.join(project_dir, 'images', 'train'))

    with open(os.path.join(project_dir, 'images', 'train', 'a.jpg'), 'w') as f:
        f.write('dummy')

    with isolated_app.app_context():
        p = Project(name="Proj", root_path=project_dir)
        db.session.add(p)
        db.session.commit()

        # 1. Manually create legacy record
        v = View(name="View1", project_id=p.id)
        tag = Tag(name="Cat", project_id=p.id)
        db.session.add(v)
        db.session.add(tag)
        db.session.commit()

        legacy_img = Image(
            filename='a.jpg',
            project_id=p.id,
            is_reviewed=True,
            flag_status='Flagged',
            split_type='train',
            view_id=v.id
        )
        legacy_img.tags.append(tag)
        db.session.add(legacy_img)
        db.session.commit()

        # 2. Add modern record to simulate collision state (partial migration)
        # In a real scenario, this happens if someone scanned before and the legacy wasn't cleanly migrated
        modern_img = Image(
            filename='images/train/a.jpg',
            project_id=p.id,
            is_reviewed=False, # should become True
            flag_status='Normal', # should become Flagged
            split_type='val', # already has one, shouldn't overwrite unless empty, wait we set it to 'train'
            view_id=None # should become v.id
        )
        db.session.add(modern_img)
        db.session.commit()

        # Clear identity maps
        modern_id = modern_img.id
        db.session.expire_all()

        # Run scan
        utils.scan_and_sync_images(p)

        # Verify legacy is deleted
        assert Image.query.filter_by(filename='a.jpg').first() is None

        # Verify modern record inherited metadata
        migrated_img = Image.query.get(modern_id)
        assert migrated_img.is_reviewed is True
        assert migrated_img.flag_status == 'Flagged'
        assert migrated_img.view_id == v.id
        # tags union
        assert len(migrated_img.tags) == 1
        assert migrated_img.tags[0].name == 'Cat'
