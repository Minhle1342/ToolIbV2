import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app

from artifact_object_store import ObjectStoreError
from models import (
    db,
    AIModel,
    ModelArtifact,
    TrainingBatch,
    TrainingCheckpoint,
    TrainingDataset,
    TrainingJob,
    TrainingJobAttempt,
    TrainingJobEvent,
    TrainingQueueTask,
)
from training_control_plane import TERMINAL_TASK_STATUSES, checkpoint_store


DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650
TERMINAL_BATCH_STATUSES = {
    'succeeded',
    'failed',
    'cancelled',
    'partial_failed',
}
TERMINAL_JOB_STATUSES = {'succeeded', 'failed'}
DELETABLE_DATASET_STATUSES = {
    'prepared',
    'uploaded',
    'failed',
    'upload_failed',
}


def normalize_retention_days(value):
    if isinstance(value, bool):
        raise ValueError('retention_days must be an integer.')
    try:
        days = int(value if value not in (None, '') else DEFAULT_RETENTION_DAYS)
    except (TypeError, ValueError) as exc:
        raise ValueError('retention_days must be an integer.') from exc
    if days < 0 or days > MAX_RETENTION_DAYS:
        raise ValueError(
            f'retention_days must be between 0 and {MAX_RETENTION_DAYS}.'
        )
    return days


def _record_timestamp(record):
    for field_name in ('finished_at', 'updated_at', 'created_at'):
        value = getattr(record, field_name, None)
        if value is not None:
            return value
    return None


def _is_old_enough(record, cutoff):
    timestamp = _record_timestamp(record)
    return timestamp is not None and timestamp <= cutoff


def _directory_size(path):
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob('*'):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _configured_root(config_key, default_name):
    return Path(
        current_app.config.get(
            config_key,
            os.path.join(os.path.dirname(__file__), default_name),
        )
    ).resolve()


def _safe_child(root, child_name):
    root = Path(root).resolve()
    child = (root / str(child_name)).resolve()
    try:
        child.relative_to(root)
    except ValueError as exc:
        raise ValueError(f'Cleanup path is outside its configured root: {child}') from exc
    if child == root:
        raise ValueError(f'Refusing to clean a storage root directly: {root}')
    return child


def _artifact_object_entries(job):
    artifacts = job.artifacts if isinstance(job.artifacts, dict) else {}
    objects = artifacts.get('_objects')
    if not isinstance(objects, dict):
        return []
    entries = []
    for payload in objects.values():
        if not isinstance(payload, dict):
            continue
        object_key = str(payload.get('object_key') or '').strip()
        if not object_key:
            continue
        try:
            size_bytes = max(int(payload.get('size_bytes') or 0), 0)
        except (TypeError, ValueError):
            size_bytes = 0
        entries.append((object_key, size_bytes))
    return entries


def _batch_cleanup_item(batch, batch_tasks, reason, model_ids=None):
    return {
        'id': batch.id,
        'batch_id': batch.batch_id,
        'name': batch.name,
        'status': batch.status,
        'tasks': len(batch_tasks),
        'finished_at': (
            batch.finished_at.isoformat() if batch.finished_at else None
        ),
        'reason': reason,
        'model_ids': sorted(model_ids or []),
    }


def _dataset_cleanup_item(dataset, reason):
    return {
        'id': dataset.id,
        'dataset_id': dataset.dataset_id,
        'status': dataset.status,
        'archive_size': int(dataset.archive_size or 0),
        'created_at': (
            dataset.created_at.isoformat() if dataset.created_at else None
        ),
        'reason': reason,
    }


def _build_cleanup_state(retention_days):
    retention_days = normalize_retention_days(retention_days)
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    batches = TrainingBatch.query.order_by(TrainingBatch.id.asc()).all()
    tasks = TrainingQueueTask.query.order_by(TrainingQueueTask.id.asc()).all()
    jobs = TrainingJob.query.order_by(TrainingJob.id.asc()).all()
    datasets = TrainingDataset.query.order_by(TrainingDataset.id.asc()).all()
    checkpoints = TrainingCheckpoint.query.order_by(
        TrainingCheckpoint.id.asc()
    ).all()
    attempts = TrainingJobAttempt.query.order_by(TrainingJobAttempt.id.asc()).all()
    events = TrainingJobEvent.query.order_by(TrainingJobEvent.id.asc()).all()
    model_artifacts = ModelArtifact.query.order_by(ModelArtifact.id.asc()).all()

    tasks_by_batch = {}
    for task in tasks:
        tasks_by_batch.setdefault(task.batch_id, []).append(task)
    checkpoints_by_task = {}
    for checkpoint in checkpoints:
        checkpoints_by_task.setdefault(checkpoint.task_id, []).append(checkpoint)
    attempts_by_task = {}
    for attempt in attempts:
        attempts_by_task.setdefault(attempt.task_id, []).append(attempt)
    events_by_task = {}
    for event in events:
        events_by_task.setdefault(event.task_id, []).append(event)
    jobs_by_id = {job.id: job for job in jobs}

    protected_task_ids = {
        task.id for task in tasks if task.imported_model_id is not None
    }
    protected_task_uuids = {
        str(task.task_id) for task in tasks if task.imported_model_id is not None
    }
    model_object_keys = {
        artifact.object_key
        for artifact in model_artifacts
        if artifact.object_key
    }
    artifact_root = _configured_root('TRAINING_ARTIFACT_ROOT', 'training_artifacts')
    for artifact in model_artifacts:
        metadata = artifact.metadata_json or {}
        task_id = str(metadata.get('task_id') or '').strip()
        if task_id:
            protected_task_uuids.add(task_id)
        if artifact.storage_path:
            artifact_path = Path(artifact.storage_path).resolve()
            try:
                relative_path = artifact_path.relative_to(artifact_root)
            except ValueError:
                continue
            if relative_path.parts:
                protected_task_uuids.add(relative_path.parts[0])
    protected_task_ids.update(
        task.id for task in tasks if task.task_id in protected_task_uuids
    )

    candidate_batches = []
    protected_batches = {
        'active_or_nonterminal': 0,
        'recent': 0,
        'imported_model': 0,
    }
    protected_batch_items = []
    candidate_task_ids = set()
    candidate_job_ids = set()
    for batch in batches:
        batch_tasks = tasks_by_batch.get(batch.id, [])
        if (
            batch.status not in TERMINAL_BATCH_STATUSES
            or any(task.status not in TERMINAL_TASK_STATUSES for task in batch_tasks)
        ):
            protected_batches['active_or_nonterminal'] += 1
            protected_batch_items.append(_batch_cleanup_item(
                batch,
                batch_tasks,
                'active_or_nonterminal',
            ))
            continue
        if not _is_old_enough(batch, cutoff):
            protected_batches['recent'] += 1
            protected_batch_items.append(_batch_cleanup_item(
                batch,
                batch_tasks,
                'recent',
            ))
            continue
        if any(task.id in protected_task_ids for task in batch_tasks):
            protected_batches['imported_model'] += 1
            protected_batch_items.append(_batch_cleanup_item(
                batch,
                batch_tasks,
                'imported_model',
                {
                    task.imported_model_id for task in batch_tasks
                    if task.imported_model_id is not None
                },
            ))
            continue

        batch_jobs = [
            jobs_by_id[task.training_job_id]
            for task in batch_tasks
            if task.training_job_id in jobs_by_id
        ]
        if any(job.imported_model_id is not None for job in batch_jobs):
            protected_batches['imported_model'] += 1
            protected_batch_items.append(_batch_cleanup_item(
                batch,
                batch_tasks,
                'imported_model',
                {
                    job.imported_model_id for job in batch_jobs
                    if job.imported_model_id is not None
                },
            ))
            continue
        batch_object_keys = {
            checkpoint.object_key
            for task in batch_tasks
            for checkpoint in checkpoints_by_task.get(task.id, [])
            if checkpoint.object_key
        }
        batch_object_keys.update(
            object_key
            for job in batch_jobs
            for object_key, _size in _artifact_object_entries(job)
        )
        if batch_object_keys & model_object_keys:
            protected_batches['imported_model'] += 1
            protected_batch_items.append(_batch_cleanup_item(
                batch,
                batch_tasks,
                'imported_model',
            ))
            continue

        candidate_batches.append((batch, batch_tasks, batch_jobs))
        candidate_task_ids.update(task.id for task in batch_tasks)
        candidate_job_ids.update(job.id for job in batch_jobs)

    linked_job_ids = {
        task.training_job_id for task in tasks if task.training_job_id is not None
    }
    orphan_jobs = [
        job
        for job in jobs
        if (
            job.id not in linked_job_ids
            and job.imported_model_id is None
            and job.status in TERMINAL_JOB_STATUSES
            and _is_old_enough(job, cutoff)
        )
    ]
    candidate_job_ids.update(job.id for job in orphan_jobs)

    superseded_checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if (
            checkpoint.task_id not in candidate_task_ids
            and checkpoint.status == 'superseded'
            and _is_old_enough(checkpoint, cutoff)
            and checkpoint.object_key not in model_object_keys
        )
    ]

    model_dataset_ids = {
        model.training_dataset_id
        for model in AIModel.query.with_entities(AIModel.training_dataset_id).all()
        if model.training_dataset_id is not None
    }
    candidate_batch_ids = {batch.id for batch, _tasks, _jobs in candidate_batches}
    candidate_dataset_ids = set()
    candidate_datasets = []
    candidate_dataset_paths = {}
    protected_datasets = {
        'referenced': 0,
        'recent_or_nonterminal': 0,
        'unsafe_storage_path': 0,
    }
    protected_dataset_items = []
    dataset_root = _configured_root('TRAINING_DATASET_ROOT', 'training_datasets')
    for dataset in datasets:
        if (
            dataset.status not in DELETABLE_DATASET_STATUSES
            or not _is_old_enough(dataset, cutoff)
        ):
            protected_datasets['recent_or_nonterminal'] += 1
            protected_dataset_items.append(_dataset_cleanup_item(
                dataset,
                'recent_or_nonterminal',
            ))
            continue
        referenced = (
            dataset.id in model_dataset_ids
            or any(
                task.training_dataset_id == dataset.id
                and task.id not in candidate_task_ids
                for task in tasks
            )
            or any(
                batch.training_dataset_id == dataset.id
                and batch.id not in candidate_batch_ids
                for batch in batches
            )
            or any(
                job.training_dataset_id == dataset.id
                and job.id not in candidate_job_ids
                for job in jobs
            )
        )
        if referenced:
            protected_datasets['referenced'] += 1
            protected_dataset_items.append(_dataset_cleanup_item(
                dataset,
                'referenced',
            ))
            continue
        snapshot_path = _safe_child(dataset_root, dataset.dataset_id)
        if dataset.archive_path:
            archive_parent = Path(dataset.archive_path).resolve().parent
            if (
                archive_parent.name != dataset.dataset_id
                or not _is_within(archive_parent, dataset_root)
            ):
                protected_datasets['unsafe_storage_path'] += 1
                protected_dataset_items.append(_dataset_cleanup_item(
                    dataset,
                    'unsafe_storage_path',
                ))
                continue
            snapshot_path = archive_parent
        candidate_dataset_ids.add(dataset.id)
        candidate_datasets.append(dataset)
        candidate_dataset_paths[dataset.id] = snapshot_path

    object_references = {}

    def add_object_reference(object_key, reference, size_bytes=0):
        object_key = str(object_key or '').strip()
        if not object_key:
            return
        entry = object_references.setdefault(
            object_key,
            {'references': set(), 'size_bytes': 0},
        )
        entry['references'].add(reference)
        entry['size_bytes'] = max(entry['size_bytes'], int(size_bytes or 0))

    for checkpoint in checkpoints:
        add_object_reference(
            checkpoint.object_key,
            ('checkpoint', checkpoint.id),
            checkpoint.size_bytes,
        )
    for job in jobs:
        for object_key, size_bytes in _artifact_object_entries(job):
            add_object_reference(object_key, ('job', job.id), size_bytes)
    for dataset in datasets:
        add_object_reference(
            dataset.object_key,
            ('dataset', dataset.id),
            dataset.archive_size,
        )
    for artifact in model_artifacts:
        add_object_reference(
            artifact.object_key,
            ('model_artifact', artifact.id),
            artifact.size_bytes,
        )

    deletable_references = {
        *(('checkpoint', checkpoint.id) for checkpoint in superseded_checkpoints),
        *(('checkpoint', checkpoint.id) for checkpoint in checkpoints if checkpoint.task_id in candidate_task_ids),
        *(('job', job_id) for job_id in candidate_job_ids),
        *(('dataset', dataset_id) for dataset_id in candidate_dataset_ids),
    }
    object_entries = {
        object_key: entry['size_bytes']
        for object_key, entry in object_references.items()
        if entry['references'] and entry['references'].issubset(deletable_references)
    }

    local_entries = {}
    local_entries_by_batch = {}
    for _batch, batch_tasks, _batch_jobs in candidate_batches:
        batch_entries = {}
        for task in batch_tasks:
            path = _safe_child(artifact_root, task.task_id)
            if path.exists():
                batch_entries[str(path)] = _directory_size(path)
        local_entries_by_batch[_batch.id] = batch_entries
        local_entries.update(batch_entries)
    local_entries_by_dataset = {}
    for dataset in candidate_datasets:
        path = candidate_dataset_paths[dataset.id]
        if path.exists():
            local_entries_by_dataset[dataset.id] = {
                str(path): _directory_size(path)
            }
            local_entries.update(local_entries_by_dataset[dataset.id])

    candidate_attempt_ids = {
        attempt.id
        for task_id in candidate_task_ids
        for attempt in attempts_by_task.get(task_id, [])
    }
    candidate_event_ids = {
        event.id
        for task_id in candidate_task_ids
        for event in events_by_task.get(task_id, [])
    }
    candidate_checkpoint_ids = {
        checkpoint.id
        for task_id in candidate_task_ids
        for checkpoint in checkpoints_by_task.get(task_id, [])
    }
    candidate_checkpoint_ids.update(
        checkpoint.id for checkpoint in superseded_checkpoints
    )

    database_rows = (
        len(candidate_batch_ids)
        + len(candidate_task_ids)
        + len(candidate_job_ids)
        + len(candidate_dataset_ids)
        + len(candidate_attempt_ids)
        + len(candidate_event_ids)
        + len(candidate_checkpoint_ids)
    )
    storage_error = None
    try:
        store = checkpoint_store()
        object_store_enabled = bool(store.enabled)
        object_store_backend = store.backend_name
    except ObjectStoreError as exc:
        storage_error = str(exc)
        object_store_enabled = False
        object_store_backend = 'error'
    public_plan = {
        'retention_days': retention_days,
        'cutoff': cutoff.isoformat(),
        'can_execute': bool(object_store_enabled or not object_entries),
        'storage': {
            'object_store_enabled': object_store_enabled,
            'object_store_backend': object_store_backend,
            'error': storage_error,
        },
        'summary': {
            'batches': len(candidate_batch_ids),
            'tasks': len(candidate_task_ids),
            'jobs': len(candidate_job_ids),
            'datasets': len(candidate_dataset_ids),
            'attempts': len(candidate_attempt_ids),
            'events': len(candidate_event_ids),
            'checkpoints': len(candidate_checkpoint_ids),
            'database_rows': database_rows,
            'local_paths': len(local_entries),
            'local_bytes': sum(local_entries.values()),
            'object_keys': len(object_entries),
            'object_bytes': sum(object_entries.values()),
        },
        'protected': {
            'batches': protected_batches,
            'datasets': protected_datasets,
            'models': AIModel.query.count(),
        },
        'items': {
            'batches': [
                _batch_cleanup_item(batch, batch_tasks, 'safe_to_delete')
                for batch, batch_tasks, _batch_jobs in candidate_batches
            ],
            'datasets': [
                _dataset_cleanup_item(dataset, 'safe_to_delete')
                for dataset in candidate_datasets
            ],
            'orphan_jobs': [
                {
                    'id': job.id,
                    'remote_job_id': job.remote_job_id,
                    'status': job.status,
                    'finished_at': (
                        job.finished_at.isoformat() if job.finished_at else None
                    ),
                }
                for job in orphan_jobs
            ],
            'superseded_checkpoints': [
                {
                    'id': checkpoint.id,
                    'checkpoint_id': checkpoint.checkpoint_id,
                    'epoch': checkpoint.epoch,
                    'size_bytes': int(checkpoint.size_bytes or 0),
                }
                for checkpoint in superseded_checkpoints
            ],
        },
        'protected_items': {
            'batches': protected_batch_items,
            'datasets': protected_dataset_items,
        },
    }
    return {
        'public': public_plan,
        'batch_ids': candidate_batch_ids,
        'task_ids': candidate_task_ids,
        'job_ids': candidate_job_ids,
        'dataset_ids': candidate_dataset_ids,
        'attempt_ids': candidate_attempt_ids,
        'event_ids': candidate_event_ids,
        'checkpoint_ids': candidate_checkpoint_ids,
        'object_entries': object_entries,
        'object_references': object_references,
        'local_entries': local_entries,
        'local_entries_by_batch': local_entries_by_batch,
        'local_entries_by_dataset': local_entries_by_dataset,
        'candidate_batches': candidate_batches,
        'candidate_datasets': candidate_datasets,
        'orphan_jobs': orphan_jobs,
        'superseded_checkpoints': superseded_checkpoints,
        'batches': batches,
        'tasks': tasks,
        'jobs': jobs,
    }


def build_training_storage_cleanup_plan(retention_days=DEFAULT_RETENTION_DAYS):
    return _build_cleanup_state(retention_days)['public']


def _selected_ids(selection, key, allowed_ids):
    if selection is None:
        return set(allowed_ids)
    values = selection.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f'selection.{key} must be a list.')
    selected = set()
    for value in values:
        if isinstance(value, bool):
            raise ValueError(f'selection.{key} must contain integer IDs.')
        try:
            selected.add(int(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f'selection.{key} must contain integer IDs.'
            ) from exc
    unknown = selected - set(allowed_ids)
    if unknown:
        raise ValueError(
            f'selection.{key} contains items that are not safe to delete: '
            + ', '.join(str(value) for value in sorted(unknown))
        )
    return selected


def _selected_cleanup_state(state, selection):
    if selection is not None and not isinstance(selection, dict):
        raise ValueError('selection must be an object.')
    if selection is not None:
        allowed_keys = {
            'batches',
            'datasets',
            'orphan_jobs',
            'superseded_checkpoints',
        }
        unknown_keys = set(selection) - allowed_keys
        if unknown_keys:
            raise ValueError(
                'selection contains unknown fields: '
                + ', '.join(sorted(unknown_keys))
            )

    batches_by_id = {
        batch.id: (batch, batch_tasks, batch_jobs)
        for batch, batch_tasks, batch_jobs in state['candidate_batches']
    }
    datasets_by_id = {
        dataset.id: dataset for dataset in state['candidate_datasets']
    }
    orphan_jobs_by_id = {job.id: job for job in state['orphan_jobs']}
    checkpoints_by_id = {
        checkpoint.id: checkpoint for checkpoint in state['superseded_checkpoints']
    }
    selected_batch_ids = _selected_ids(
        selection,
        'batches',
        batches_by_id,
    )
    selected_dataset_ids = _selected_ids(
        selection,
        'datasets',
        datasets_by_id,
    )
    selected_orphan_job_ids = _selected_ids(
        selection,
        'orphan_jobs',
        orphan_jobs_by_id,
    )
    selected_superseded_checkpoint_ids = _selected_ids(
        selection,
        'superseded_checkpoints',
        checkpoints_by_id,
    )

    selected_task_ids = set()
    selected_batch_job_ids = set()
    for batch_id in selected_batch_ids:
        _batch, batch_tasks, batch_jobs = batches_by_id[batch_id]
        selected_task_ids.update(task.id for task in batch_tasks)
        selected_batch_job_ids.update(job.id for job in batch_jobs)
    selected_job_ids = selected_batch_job_ids | selected_orphan_job_ids
    selected_attempt_ids = {
        attempt_id
        for task_id in selected_task_ids
        for attempt_id in (
            attempt.id for attempt in TrainingJobAttempt.query.filter_by(
                task_id=task_id
            ).all()
        )
    }
    selected_event_ids = {
        event.id for event in TrainingJobEvent.query.filter(
            TrainingJobEvent.task_id.in_(selected_task_ids)
        ).all()
    } if selected_task_ids else set()
    selected_checkpoint_ids = {
        checkpoint.id for checkpoint in TrainingCheckpoint.query.filter(
            TrainingCheckpoint.task_id.in_(selected_task_ids)
        ).all()
    } if selected_task_ids else set()
    selected_checkpoint_ids.update(selected_superseded_checkpoint_ids)

    for dataset_id in selected_dataset_ids:
        still_referenced = (
            any(
                batch.training_dataset_id == dataset_id
                and batch.id not in selected_batch_ids
                for batch in state['batches']
            )
            or any(
                task.training_dataset_id == dataset_id
                and task.id not in selected_task_ids
                for task in state['tasks']
            )
            or any(
                job.training_dataset_id == dataset_id
                and job.id not in selected_job_ids
                for job in state['jobs']
            )
        )
        if still_referenced:
            raise ValueError(
                f'Dataset {dataset_id} is still referenced by training history. '
                'Select its completed batch too, or keep the dataset.'
            )

    deletable_references = {
        *(('checkpoint', checkpoint_id) for checkpoint_id in selected_checkpoint_ids),
        *(('job', job_id) for job_id in selected_job_ids),
        *(('dataset', dataset_id) for dataset_id in selected_dataset_ids),
    }
    object_entries = {
        object_key: entry['size_bytes']
        for object_key, entry in state['object_references'].items()
        if entry['references'] and entry['references'].issubset(deletable_references)
    }
    local_entries = {}
    for batch_id in selected_batch_ids:
        local_entries.update(state['local_entries_by_batch'].get(batch_id, {}))
    for dataset_id in selected_dataset_ids:
        local_entries.update(state['local_entries_by_dataset'].get(dataset_id, {}))
    summary = {
        'batches': len(selected_batch_ids),
        'tasks': len(selected_task_ids),
        'jobs': len(selected_job_ids),
        'datasets': len(selected_dataset_ids),
        'attempts': len(selected_attempt_ids),
        'events': len(selected_event_ids),
        'checkpoints': len(selected_checkpoint_ids),
        'database_rows': (
            len(selected_batch_ids)
            + len(selected_task_ids)
            + len(selected_job_ids)
            + len(selected_dataset_ids)
            + len(selected_attempt_ids)
            + len(selected_event_ids)
            + len(selected_checkpoint_ids)
        ),
        'local_paths': len(local_entries),
        'local_bytes': sum(local_entries.values()),
        'object_keys': len(object_entries),
        'object_bytes': sum(object_entries.values()),
    }
    return {
        'batch_ids': selected_batch_ids,
        'task_ids': selected_task_ids,
        'job_ids': selected_job_ids,
        'dataset_ids': selected_dataset_ids,
        'attempt_ids': selected_attempt_ids,
        'event_ids': selected_event_ids,
        'checkpoint_ids': selected_checkpoint_ids,
        'object_entries': object_entries,
        'local_entries': local_entries,
        'summary': summary,
    }


def _delete_object_entries(object_entries):
    if not object_entries:
        return
    store = checkpoint_store()
    if not store.enabled:
        raise ObjectStoreError(
            'Object storage is disabled, but the cleanup plan contains R2 objects.'
        )
    for object_key in sorted(object_entries):
        store.delete(object_key)


def _delete_local_entries(local_entries):
    for raw_path in sorted(local_entries, key=len, reverse=True):
        path = Path(raw_path)
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def execute_training_storage_cleanup(
    retention_days=DEFAULT_RETENTION_DAYS,
    selection=None,
):
    state = _build_cleanup_state(retention_days)
    plan = state['public']
    selected = _selected_cleanup_state(state, selection)
    _delete_object_entries(selected['object_entries'])
    _delete_local_entries(selected['local_entries'])

    if selected['checkpoint_ids']:
        TrainingCheckpoint.query.filter(
            TrainingCheckpoint.id.in_(selected['checkpoint_ids'])
        ).delete(synchronize_session=False)
    if selected['event_ids']:
        TrainingJobEvent.query.filter(
            TrainingJobEvent.id.in_(selected['event_ids'])
        ).delete(synchronize_session=False)
    if selected['attempt_ids']:
        TrainingJobAttempt.query.filter(
            TrainingJobAttempt.id.in_(selected['attempt_ids'])
        ).delete(synchronize_session=False)
    if selected['task_ids']:
        TrainingQueueTask.query.filter(
            TrainingQueueTask.id.in_(selected['task_ids'])
        ).delete(synchronize_session=False)
    if selected['batch_ids']:
        TrainingBatch.query.filter(
            TrainingBatch.id.in_(selected['batch_ids'])
        ).delete(synchronize_session=False)
    if selected['job_ids']:
        TrainingJob.query.filter(
            TrainingJob.id.in_(selected['job_ids'])
        ).delete(synchronize_session=False)
    if selected['dataset_ids']:
        TrainingDataset.query.filter(
            TrainingDataset.id.in_(selected['dataset_ids'])
        ).delete(synchronize_session=False)
    db.session.commit()

    current_app.logger.info(
        'Training storage cleanup completed',
        extra={
            'retention_days': plan['retention_days'],
            **selected['summary'],
        },
    )
    return {
        'message': 'Training storage cleanup completed.',
        'deleted': selected['summary'],
        'retention_days': plan['retention_days'],
        'cutoff': plan['cutoff'],
    }


def cleanup_model_storage(model):
    artifacts = list(model.artifacts)
    artifact_ids = {artifact.id for artifact in artifacts}
    object_entries = {}
    local_paths = set()

    for artifact in artifacts:
        if artifact.object_key:
            shared_object = ModelArtifact.query.filter(
                ModelArtifact.object_key == artifact.object_key,
                ~ModelArtifact.id.in_(artifact_ids),
            ).first()
            if shared_object is None:
                object_entries[artifact.object_key] = int(artifact.size_bytes or 0)
        if artifact.storage_path:
            shared_path = ModelArtifact.query.filter(
                ModelArtifact.storage_path == artifact.storage_path,
                ~ModelArtifact.id.in_(artifact_ids),
            ).first()
            if shared_path is None:
                local_paths.add(Path(artifact.storage_path).resolve())

    model_root = _configured_root('MODEL_STORAGE_ROOT', 'models')
    artifact_roots = (
        model_root,
        _configured_root('MODEL_ARTIFACT_ROOT', 'model_artifacts'),
        _configured_root('TRAINING_ARTIFACT_ROOT', 'training_artifacts'),
    )
    runtime_path = (model_root / model.filename).resolve()
    try:
        runtime_path.relative_to(model_root)
    except ValueError as exc:
        raise ValueError('Model runtime path is outside MODEL_STORAGE_ROOT.') from exc
    local_paths.add(runtime_path)

    for path in local_paths:
        if not any(_is_within(path, root) for root in artifact_roots):
            raise ValueError(f'Model artifact path is outside configured roots: {path}')

    existing_local_paths = {path for path in local_paths if path.is_file()}
    _delete_object_entries(object_entries)
    deleted_local_bytes = 0
    for path in sorted(local_paths, key=lambda item: len(str(item)), reverse=True):
        if not path.is_file():
            continue
        deleted_local_bytes += path.stat().st_size
        path.unlink()
        for root in artifact_roots:
            if _is_within(path, root):
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
                break
    return {
        'local_files': len(existing_local_paths),
        'local_bytes': deleted_local_bytes,
        'object_keys': len(object_entries),
        'object_bytes': sum(object_entries.values()),
    }


def _is_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False
