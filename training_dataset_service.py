import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from models import db, Project, TrainingDataset
import utils
try:
    from clear_header import validate_and_rename_yolo_dataset
except ModuleNotFoundError:
    from scripts.clear_header import validate_and_rename_yolo_dataset


def default_clear_header_callback(export_path):
    import contextlib
    import io

    cleaned_splits = []
    split_layouts = [
        (
            split,
            os.path.join(export_path, 'images', split),
            os.path.join(export_path, 'labels', split),
        )
        for split in ('train', 'val', 'test')
    ] + [
        (
            split,
            os.path.join(export_path, split, 'images'),
            os.path.join(export_path, split, 'labels'),
        )
        for split in ('train', 'val', 'test')
    ]
    for split, image_path, label_path in split_layouts:
        if not os.path.isdir(image_path) or not os.path.isdir(label_path):
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            validate_and_rename_yolo_dataset(image_path, label_path, dry_run=False)
        cleaned_splits.append(split)
    return cleaned_splits


def build_training_dataset_paths(dataset_id, storage_root):
    normalized_id = str(uuid.UUID(str(dataset_id)))
    normalized_storage_root = Path(storage_root).resolve()
    snapshot_root = (normalized_storage_root / normalized_id).resolve()
    try:
        snapshot_root.relative_to(normalized_storage_root)
    except ValueError as exc:
        raise ValueError('Invalid training dataset storage path.') from exc
    return {
        'root': snapshot_root,
        'dataset': snapshot_root / 'dataset',
        'archive': snapshot_root / 'dataset.zip',
        'manifest': snapshot_root / 'manifest.json',
    }


def sha256_path(path):
    import hashlib

    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_training_dataset_snapshot(
    *,
    project_id,
    splits,
    include_unlabeled,
    exclude_flagged,
    storage_root,
    clear_header_callback,
):
    project = db.session.get(Project, project_id)
    if project is None:
        raise LookupError('Project not found.')

    dataset_uuid = str(uuid.uuid4())
    paths = build_training_dataset_paths(dataset_uuid, storage_root)
    dataset = TrainingDataset(
        dataset_id=dataset_uuid,
        project_id=project.id,
        status='exporting',
        split_config=dict(splits),
    )
    db.session.add(dataset)
    db.session.commit()

    try:
        paths['root'].mkdir(parents=True, exist_ok=False)
        result = utils.export_dataset(
            {
                'project_ids': [project.id],
                'include_unlabeled': include_unlabeled,
                'exclude_flagged': exclude_flagged,
            },
            splits=splits,
            format='yolo',
            output_dir=str(paths['dataset']),
        )
        if result.get('status') != 'success':
            raise ValueError(result.get('message') or 'Dataset export failed.')

        clear_header_callback(str(paths['dataset']))
        stats = result.get('stats') or {}
        if int(stats.get('train') or 0) <= 0:
            raise ValueError('The exported train split contains no images.')
        if int(stats.get('val') or 0) <= 0:
            raise ValueError(
                'The exported val split contains no images. '
                'Add more labeled images or adjust the split.'
            )

        class_names = utils.get_classes(project)
        if not class_names:
            raise ValueError('The project does not define any classes.')

        manifest = {
            'dataset_id': dataset_uuid,
            'project_id': project.id,
            'project_name': project.name,
            'splits': dict(splits),
            'stats': stats,
            'class_names': class_names,
            'include_unlabeled': include_unlabeled,
            'exclude_flagged': exclude_flagged,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        paths['manifest'].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        shutil.copy2(paths['manifest'], paths['dataset'] / 'toolib_manifest.json')
        archive_path = shutil.make_archive(
            str(paths['archive'].with_suffix('')),
            'zip',
            root_dir=str(paths['dataset']),
        )

        dataset.status = 'prepared'
        dataset.archive_path = str(Path(archive_path).resolve())
        dataset.archive_sha256 = sha256_path(archive_path)
        dataset.archive_size = os.path.getsize(archive_path)
        dataset.train_count = int(stats.get('train') or 0)
        dataset.val_count = int(stats.get('val') or 0)
        dataset.test_count = int(stats.get('test') or 0)
        dataset.total_count = int(stats.get('total') or 0)
        dataset.class_names = list(class_names)
        dataset.error = None
        db.session.commit()
        return dataset
    except Exception as exc:
        current_app.logger.exception(
            'Could not prepare training dataset snapshot',
            extra={
                'dataset_id': dataset_uuid,
                'project_id': project.id,
            },
        )
        db.session.rollback()
        persisted = db.session.get(TrainingDataset, dataset.id)
        if persisted is not None:
            persisted.status = 'failed'
            persisted.error = str(exc)[:8000]
            db.session.commit()
        raise
