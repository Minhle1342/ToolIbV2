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
        '"Await failover"',
    ):
        assert expected in source
