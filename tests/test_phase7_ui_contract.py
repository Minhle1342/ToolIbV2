from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COLAB_MANAGER = REPOSITORY_ROOT / 'templates' / 'colab_manager.html'


def test_colab_manager_displays_checkpoint_and_resume_state():
    source = COLAB_MANAGER.read_text(encoding='utf-8')

    for expected in (
        'id="trainingStatusObjectStore"',
        'status.object_store?.enabled',
        'if (task.latest_checkpoint)',
        'Checkpoint epoch ${checkpoint.epoch}/${checkpoint.total_epochs}',
        'resume ${task.resume_count}/${task.max_resume_count}',
        'latestAttempt.attempt_kind || "initial"',
        'latestAttempt.resumed_from_epoch',
        '"Chờ kết nối lại"',
    ):
        assert expected in source


def test_colab_manager_keeps_current_status_message_after_transient_error():
    source = COLAB_MANAGER.read_text(encoding='utf-8')

    assert 'const TRAINING_TASK_ERROR_STATUSES = new Set([' in source
    assert 'TRAINING_TASK_ERROR_STATUSES.has(task.status)' in source
    assert 'message.textContent = trainingTaskMessage(task);' in source


def test_colab_manager_preserves_open_technical_details_during_refresh():
    source = COLAB_MANAGER.read_text(encoding='utf-8')

    for expected in (
        'const trainingTechnicalDetailsOpen = new Set();',
        'technicalDetails.dataset.trainingDetailsKey = technicalDetailsKey;',
        'technicalDetails.open = trainingTechnicalDetailsOpen.has(technicalDetailsKey);',
        'technicalDetails.addEventListener("toggle", () => {',
        'trainingTechnicalDetailsOpen.add(technicalDetailsKey);',
        'trainingTechnicalDetailsOpen.delete(technicalDetailsKey);',
    ):
        assert expected in source


def test_fresh_training_publishes_dataset_before_creating_queue_tasks():
    source = COLAB_MANAGER.read_text(encoding='utf-8')

    for expected in (
        'const datasetIdsByProject = new Map();',
        '`/api/training-datasets/${prepared.id}/publish`',
        'training_dataset_id: datasetIdsByProject.get(projectId)',
        'Dataset đã sẵn sàng trên R2 · đang tạo hàng đợi...',
    ):
        assert expected in source
